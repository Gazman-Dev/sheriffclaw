from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

from shared.llm.providers import ChatGPTSubscriptionCodexProvider, OpenAICodexProvider, StubProvider, TestProvider
from shared.llm.registry import resolve_model
from shared.paths import base_root
from shared.proc_rpc import ProcClient
from shared.skills.loader import SkillLoader


def _local_now() -> datetime:
    return datetime.now().astimezone()


class WorkerRuntime:
    MAX_TOOL_ROUNDS = 8
    MAX_CHILDREN_PER_TURN = 3
    MAX_CHILD_SECONDS = 1200

    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.providers: dict[str, object] = {}
        self._child_count_by_turn: dict[str, int] = {}
        self._spawn_depth: dict[str, int] = {}

        self.repo_root = Path(__file__).resolve().parents[2]
        self.agent_workspace = base_root() / "agent_workspace"
        self.agent_workspace.mkdir(parents=True, exist_ok=True)

        self.conversation_dir = self.agent_workspace / "conversation"
        self.conversation_dir.mkdir(parents=True, exist_ok=True)
        self.skill_loader = SkillLoader(
            user_root=self.repo_root / "skills",
            system_root=self.repo_root / "system_skills",
        )
        self.skills = self.skill_loader.load()
        self._rpc_clients: dict[str, ProcClient] = {}

    def _get_rpc(self, service: str) -> ProcClient:
        if service not in self._rpc_clients:
            self._rpc_clients[service] = ProcClient(service)
        return self._rpc_clients[service]

    def _session_state(self, handle: str) -> dict:
        state = self.sessions.get(handle)
        if state is None:
            state = {
                "tool_results": [],
                "turn_counter": 0,
                "sent_files": [],
            }
            self.sessions[handle] = state
        return state

    def _session_dir(self, session: str) -> Path:
        p = self.conversation_dir / session
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _session_system_dir(self, session: str) -> Path:
        p = self._session_dir(session) / "system"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _workspace_snapshot(self, max_entries: int = 200) -> list[str]:
        rows: list[str] = []
        for path in sorted(self.agent_workspace.rglob("*")):
            if len(rows) >= max_entries:
                rows.append("... (truncated)")
                break
            if any(part == "__pycache__" for part in path.parts):
                continue
            rel = path.relative_to(self.agent_workspace).as_posix()
            if path.is_dir():
                rows.append(f"D {rel}/")
            else:
                try:
                    sz = path.stat().st_size
                except Exception:
                    sz = -1
                rows.append(f"F {rel} ({sz} bytes)")
        return rows

    def _prompt_template_path(self, name: str) -> Path:
        return self.repo_root / "shared" / "prompts" / name

    def _read_prompt_template(self, name: str, fallback: str) -> str:
        p = self._prompt_template_path(name)
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return fallback

    @staticmethod
    def _render_template(template: str, values: dict[str, str]) -> str:
        out = template
        for k, v in values.items():
            out = out.replace(f"{{{{{k}}}}}", v)
        return out

    def _build_system_prompt(self, *, session: str, date_token: str, channel: str, text: str, tool_results: list[dict]) -> str:
        snapshot = "\n".join(self._workspace_snapshot())
        recent_tools = "\n".join(json.dumps(x, ensure_ascii=False) for x in tool_results[-8:])
        fallback = (
            "You are SheriffClaw orchestrator in a file-native runtime.\n"
            "Do not rely on chat history. Use files as source of truth.\n"
            "You can create, move, and organize files anywhere the OS sandbox allows.\n"
            "When ready for user delivery, ensure files are fully written and atomically renamed to final names.\n"
            "Then write <session>/_ready.json with: session, date, files[], final, generated_at.\n"
            "Only list delivery files located under conversation/{{session}}/ and finalized (not .tmp).\n"
            "If you need privileged external actions, use TOOL_CALL.\n"
            "To spawn helper agents use TOOL_CALL with name agents.spawn.\n"
            "Only the main agent can spawn children.\n"
            "\n"
            "Current turn metadata:\nchannel={{channel}}\nsession={{session}}\n"
            "date={{date}}\nuser_text={{user_text}}\n"
            "\n"
            "Workspace snapshot:\n"
            "{{workspace_snapshot}}\n"
            "\n"
            "Recent tool results:\n"
            "{{recent_tool_results}}\n"
        )
        tmpl = self._read_prompt_template("orchestrator_system_prompt.md", fallback)
        return self._render_template(
            tmpl,
            {
                "channel": channel,
                "session": session,
                "date": date_token,
                "user_text": text,
                "workspace_snapshot": snapshot or "(empty)",
                "recent_tool_results": recent_tools or "(none)",
            },
        )

    def _extract_tool_calls(self, text: str) -> tuple[list[dict], str]:
        calls: list[dict] = []
        cleaned = text
        start = 0
        marker = "TOOL_CALL:"
        while True:
            idx = cleaned.find(marker, start)
            if idx < 0:
                break
            brace_start = cleaned.find("{", idx)
            if brace_start < 0:
                break
            depth = 0
            brace_end = -1
            for i in range(brace_start, len(cleaned)):
                c = cleaned[i]
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        brace_end = i + 1
                        break
            if brace_end < 0:
                break
            blob = cleaned[brace_start:brace_end]
            try:
                obj = json.loads(blob)
                if isinstance(obj, dict) and "name" in obj:
                    calls.append({"name": str(obj.get("name")), "arguments": obj.get("arguments", {}) or {}})
            except Exception:
                pass
            cleaned = cleaned[:idx] + cleaned[brace_end:]
            start = idx
        return calls, cleaned.strip()

    def _acquire_seq_lock(self, session_dir: Path) -> Path:
        lock = session_dir / ".seq.lock"
        while True:
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return lock
            except FileExistsError:
                time.sleep(0.01)

    def _release_seq_lock(self, lock_path: Path) -> None:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass

    def _next_sequence(self, session_dir: Path) -> int:
        pat = re.compile(r"^(\d+)_")
        max_n = 0
        for p in session_dir.rglob("*.md"):
            m = pat.match(p.name)
            if not m:
                continue
            try:
                n = int(m.group(1))
            except Exception:
                continue
            max_n = max(max_n, n)
        return max_n + 1

    def _write_session_md_file(self, *, session: str, kind: str, body: str, subdir: str | None = None) -> Path:
        now = _local_now()
        minute_stamp = now.strftime("%Y_%m_%d_%H_%M")
        session_dir = self._session_dir(session)
        target_dir = session_dir if not subdir else (session_dir / subdir)
        target_dir.mkdir(parents=True, exist_ok=True)

        lock = self._acquire_seq_lock(session_dir)
        try:
            seq = self._next_sequence(session_dir)
            name = f"{seq}_{minute_stamp}_{kind}.md"
            out = target_dir / name
            self._atomic_write_text(out, body)
            return out
        finally:
            self._release_seq_lock(lock)

    def _write_turn_input_file(self, *, session: str, date_token: str, channel: str, text: str) -> Path:
        now = _local_now()
        body = (
            f"# User Message\n\n"
            f"- session: {session}\n"
            f"- date: {date_token}\n"
            f"- timestamp_local: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            f"- channel: {channel}\n"
            f"## text\n\n{text}\n"
        )
        return self._write_session_md_file(session=session, kind="user", body=body)

    def _atomic_write_text(self, path: Path, text: str) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def _write_assistant_output_file(self, *, session: str, date_token: str, text: str) -> Path:
        now = _local_now()
        minute_stamp = now.strftime("%Y_%m_%d_%H_%M")
        session_dir = self._session_dir(session)
        final = session_dir / f"00_{minute_stamp}_assistant.md"
        tmp = session_dir / f"00_{minute_stamp}_assistant.tmp"
        body = (
            f"# Assistant Message\n\n"
            f"- session: {session}\n"
            f"- date: {date_token}\n"
            f"- timestamp_local: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n\n"
            f"## text\n\n{text}\n"
        )
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, final)
        return final

    async def _spawn_child_agent(self, *, parent_session: str, model: str, provider, payload: dict) -> dict:
        turn_key = parent_session
        used = self._child_count_by_turn.get(turn_key, 0)
        if used >= self.MAX_CHILDREN_PER_TURN:
            return {"status": "error", "error": "spawn_limit_exceeded"}

        timeout = int(payload.get("timeout_seconds", self.MAX_CHILD_SECONDS))
        timeout = min(max(timeout, 1), self.MAX_CHILD_SECONDS)
        child_id = f"child_{uuid.uuid4().hex[:10]}"
        output_dir_raw = str(payload.get("output_dir", "")).strip()
        output_dir = Path(output_dir_raw) if output_dir_raw else (self.agent_workspace / "agents" / child_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        task = str(payload.get("task", "")).strip()
        context_paths = payload.get("context_paths", []) or []

        messages = [
            {
                "role": "system",
                "content": self._render_template(
                    self._read_prompt_template(
                        "child_agent_system_prompt.md",
                        "You are a spawned helper agent. Complete the task using files/tools and return a concise result.",
                    ),
                    {
                        "parent_session": parent_session,
                        "child_id": child_id,
                        "timeout_seconds": str(timeout),
                    },
                ),
            },
            {"role": "user", "content": f"Task: {task}\nContext paths: {context_paths}\nOutput dir: {output_dir}"},
        ]
        self._child_count_by_turn[turn_key] = used + 1
        try:
            out = await asyncio.wait_for(provider.generate(messages, model=model), timeout=timeout)
        except asyncio.TimeoutError:
            return {"status": "timeout", "child_id": child_id}
        except Exception as e:
            return {"status": "error", "child_id": child_id, "error": str(e)}

        out_file = output_dir / f"{child_id}_result.md"
        out_file.write_text(out, encoding="utf-8")
        return {"status": "ok", "child_id": child_id, "output_paths": [str(out_file)]}

    def _collect_session_response_files(self, session: str, sent_files: set[str]) -> list[Path]:
        session_dir = self._session_dir(session)
        files: list[Path] = []
        for p in sorted(session_dir.glob("00_*_*.md")):
            name = p.name.lower()
            if name.endswith("_user.md") or name.endswith("_system.md") or name.endswith("_tools.md"):
                continue
            ps = str(p.resolve())
            if ps in sent_files:
                continue
            files.append(p.resolve())
        return files

    def _write_system_prompt_file(self, *, session: str, prompt: str) -> Path:
        now = _local_now()
        body = (
            "# System Prompt\n\n"
            f"- session: {session}\n"
            f"- timestamp_local: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n\n"
            "## prompt\n\n"
            f"{prompt}\n"
        )
        return self._write_session_md_file(session=session, kind="system", body=body, subdir="system")

    async def user_message(
        self,
        session_handle: str,
        text: str,
        model_ref: str | None,
        emit_event,
        provider_name: str | None = None,
        api_key: str = "",
        base_url: str = "",
        codex_state_b64: str = "",
        channel: str = "cli",
        principal_external_id: str = "unknown",
    ):
        state = self._session_state(session_handle)
        state["turn_counter"] = int(state.get("turn_counter", 0)) + 1
        turn_no = int(state["turn_counter"])
        sent_files = set(state.get("sent_files", []))

        model = resolve_model(model_ref)
        selected_provider = provider_name or ("test" if model.startswith("test/") else "stub")
        provider = self._provider(selected_provider, api_key, base_url, codex_state_b64)

        date_token = _local_now().strftime("%Y_%m_%d")
        self._write_turn_input_file(
            session=session_handle,
            date_token=date_token,
            channel=channel,
            text=text,
        )

        messages = [
            {
                "role": "system",
                "content": self._build_system_prompt(
                    session=session_handle,
                    date_token=date_token,
                    channel=channel,
                    text=text,
                    tool_results=list(state.get("tool_results", [])),
                ),
            },
            {"role": "user", "content": text},
        ]
        self._write_system_prompt_file(session=session_handle, prompt=messages[0]["content"])

        assistant_msg = ""
        for _ in range(self.MAX_TOOL_ROUNDS):
            raw = await provider.generate(messages, model=model)
            calls, cleaned = self._extract_tool_calls(raw)
            if not calls:
                assistant_msg = cleaned or raw or "No response generated."
                break

            for c in calls:
                name = c.get("name", "")
                args = c.get("arguments", {}) or {}
                if name == "agents.spawn":
                    spawn_res = await self._spawn_child_agent(parent_session=session_handle, model=model, provider=provider, payload=args)
                    tool_entry = {"tool_name": name, "result": spawn_res}
                    state["tool_results"].append(tool_entry)
                    evt = json.dumps(tool_entry, ensure_ascii=False)
                    messages.append({"role": "tool", "content": evt})
                    continue
                await emit_event("tool.call", {"tool_name": name, "payload": args})
            if cleaned:
                assistant_msg = cleaned
                break
            if calls:
                assistant_msg = "Tool call requested."
                break

        pending_files = self._collect_session_response_files(session_handle, sent_files)
        if pending_files:
            for p in pending_files:
                try:
                    content = p.read_text(encoding="utf-8")
                except Exception as e:
                    content = f"Failed to read response file {p}: {e}"
                await emit_event("assistant.delta", {"text": content})
                await emit_event("assistant.final", {"text": content, "file_path": str(p)})
                sent_files.add(str(p))
            state["sent_files"] = sorted(sent_files)
            return

        if not assistant_msg:
            assistant_msg = f"No response files generated for turn {turn_no}."
        p = self._write_assistant_output_file(session=session_handle, date_token=date_token, text=assistant_msg)
        await emit_event("assistant.delta", {"text": assistant_msg})
        await emit_event("assistant.final", {"text": assistant_msg, "file_path": str(p)})
        sent_files.add(str(p.resolve()))
        state["sent_files"] = sorted(sent_files)

        if hasattr(provider, "last_codex_state_b64"):
            out_state = str(getattr(provider, "last_codex_state_b64") or "")
            if out_state and out_state != codex_state_b64:
                await emit_event("provider.state", {"codex_state_b64": out_state})

    async def tool_result(self, session_handle: str, tool_name: str, result: dict) -> None:
        state = self._session_state(session_handle)
        row = {"ts": _local_now().strftime("%Y-%m-%d %H:%M:%S %Z"), "tool_name": tool_name, "result": result}
        state["tool_results"].append(row)
        log = self._session_dir(session_handle) / "tool_results.jsonl"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    async def skill_run(self, name: str, payload: dict, emit_event=None) -> dict:
        self.skills = self.skill_loader.load()
        loaded = self.skills.get(name)
        if not loaded:
            return {"error": f"unknown skill: {name}"}

        cmd = loaded.command
        argv = payload.get("argv", [])
        stdin_data = payload.get("stdin", "")
        if argv:
            cmd = f"{cmd} {' '.join(argv)}"

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdin=asyncio.subprocess.PIPE if stdin_data else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.agent_workspace.resolve()),
        )
        stdout, stderr = await proc.communicate(input=stdin_data.encode("utf-8") if stdin_data else None)
        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "code": int(proc.returncode),
        }

    def _provider(self, provider: str, api_key: str, base_url: str = "", codex_state_b64: str = ""):
        if os.environ.get("SHERIFF_DEBUG", "").strip().lower() in {"1", "true", "yes"}:
            return TestProvider()
        key = f"{provider}:{api_key}:{base_url}:{hash(codex_state_b64)}"
        if key not in self.providers:
            if provider == "test":
                self.providers[key] = TestProvider()
            elif provider in {"openai-codex"}:
                self.providers[key] = OpenAICodexProvider(
                    api_key=api_key,
                    base_url=base_url or "https://api.openai.com/v1",
                    codex_state_b64=codex_state_b64,
                )
            elif provider in {"openai-codex-chatgpt"}:
                self.providers[key] = ChatGPTSubscriptionCodexProvider(
                    access_token=api_key,
                    base_url=base_url or "https://chatgpt.com/backend-api/codex",
                    codex_state_b64=codex_state_b64,
                )
            else:
                self.providers[key] = StubProvider()
        return self.providers[key]

    async def session_open(self, session_id: str | None) -> str:
        handle = "primary_session"
        self._session_state(handle)
        return handle

    async def session_close(self, session_handle: str) -> None:
        self.sessions.pop(session_handle, None)
