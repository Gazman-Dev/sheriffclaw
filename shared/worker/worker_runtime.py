from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from shared.llm.providers import ChatGPTSubscriptionCodexProvider, OpenAICodexProvider, StubProvider, TestProvider
from shared.llm.registry import resolve_model
from shared.paths import base_root
from shared.proc_rpc import ProcClient
from shared.skills.loader import SkillLoader


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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

        self.inbox_dir = self.agent_workspace / "inbox"
        self.outbox_dir = self.agent_workspace / "outbox"
        self.events_dir = self.agent_workspace / "events"
        for p in (self.inbox_dir, self.outbox_dir, self.events_dir):
            p.mkdir(parents=True, exist_ok=True)

        self.ready_manifest_path = self.outbox_dir / "_ready.json"
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
                "last_manifest": None,
                "turn_counter": 0,
            }
            self.sessions[handle] = state
        return state

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

    def _build_system_prompt(self, *, session: str, date_token: str, channel: str, principal_id: str, text: str, tool_results: list[dict]) -> str:
        snapshot = "\n".join(self._workspace_snapshot())
        recent_tools = "\n".join(json.dumps(x, ensure_ascii=False) for x in tool_results[-8:])
        return (
            "You are SheriffClaw orchestrator in a file-native runtime.\n"
            "Do not rely on chat history. Use files as source of truth.\n"
            "You can create, move, and organize files anywhere the OS sandbox allows.\n"
            "When ready for user delivery, ensure files are fully written and atomically renamed to final names.\n"
            "Then write outbox/_ready.json with: session, date, files[], final, generated_at.\n"
            f"Only list delivery files whose basename starts with '{session}_{date_token}'.\n"
            "If you need privileged external actions, use TOOL_CALL.\n"
            "To spawn helper agents use TOOL_CALL with name agents.spawn.\n"
            "Only the main agent can spawn children.\n"
            "\n"
            f"Current turn metadata:\nchannel={channel}\nprincipal={principal_id}\nsession={session}\n"
            f"date={date_token}\nuser_text={text}\n"
            "\n"
            "Workspace snapshot:\n"
            f"{snapshot or '(empty)'}\n"
            "\n"
            "Recent tool results:\n"
            f"{recent_tools or '(none)'}\n"
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

    def _write_turn_input_file(self, *, session: str, date_token: str, channel: str, principal_id: str, text: str) -> Path:
        now = _utc_now()
        ts = now.strftime("%Y%m%dT%H%M%S%fZ")
        p = self.inbox_dir / f"{session}_{date_token}_{ts}_user.md"
        body = (
            f"# User Message\n\n"
            f"- session: {session}\n"
            f"- date: {date_token}\n"
            f"- timestamp_utc: {now.isoformat()}\n"
            f"- channel: {channel}\n"
            f"- principal: {principal_id}\n\n"
            f"## text\n\n{text}\n"
        )
        p.write_text(body, encoding="utf-8")
        return p

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
                "content": (
                    "You are a spawned helper agent. Complete the task using files/tools and return a concise result."
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

    def _load_ready_manifest(self) -> dict | None:
        if not self.ready_manifest_path.exists():
            return None
        try:
            obj = json.loads(self.ready_manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        if not isinstance(obj.get("files"), list):
            return None
        return obj

    def _collect_ready_files(self, *, session: str, date_token: str, seen_manifest: dict | None) -> tuple[list[Path], dict | None]:
        manifest = self._load_ready_manifest()
        if not manifest:
            return [], None
        if seen_manifest is not None and manifest == seen_manifest:
            return [], manifest
        if str(manifest.get("session", "")) != session:
            return [], manifest
        if str(manifest.get("date", "")) != date_token:
            return [], manifest

        prefix = f"{session}_{date_token}"
        files: list[Path] = []
        for raw in manifest.get("files", []):
            if not isinstance(raw, str) or not raw.strip():
                continue
            p = Path(raw)
            if not p.is_absolute():
                p = (self.agent_workspace / p).resolve()
            name = p.name
            if not name.startswith(prefix):
                continue
            if name.endswith(".tmp"):
                continue
            if not p.exists() or not p.is_file():
                continue
            files.append(p)
        return files, manifest

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

        model = resolve_model(model_ref)
        selected_provider = provider_name or ("test" if model.startswith("test/") else "stub")
        provider = self._provider(selected_provider, api_key, base_url, codex_state_b64)

        date_token = _utc_now().strftime("%Y%m%d")
        self._write_turn_input_file(
            session=session_handle,
            date_token=date_token,
            channel=channel,
            principal_id=principal_external_id,
            text=text,
        )

        messages = [
            {
                "role": "system",
                "content": self._build_system_prompt(
                    session=session_handle,
                    date_token=date_token,
                    channel=channel,
                    principal_id=principal_external_id,
                    text=text,
                    tool_results=list(state.get("tool_results", [])),
                ),
            },
            {"role": "user", "content": text},
        ]

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

        ready_files, manifest = self._collect_ready_files(
            session=session_handle,
            date_token=date_token,
            seen_manifest=state.get("last_manifest"),
        )
        if manifest is not None:
            state["last_manifest"] = manifest

        if ready_files:
            for p in ready_files:
                try:
                    content = p.read_text(encoding="utf-8")
                except Exception as e:
                    content = f"Failed to read response file {p}: {e}"
                await emit_event("assistant.delta", {"text": content})
                await emit_event("assistant.final", {"text": content, "file_path": str(p)})
            return

        if not assistant_msg:
            assistant_msg = f"No ready response files generated for turn {turn_no}."
        await emit_event("assistant.delta", {"text": assistant_msg})
        await emit_event("assistant.final", {"text": assistant_msg})

        if hasattr(provider, "last_codex_state_b64"):
            out_state = str(getattr(provider, "last_codex_state_b64") or "")
            if out_state and out_state != codex_state_b64:
                await emit_event("provider.state", {"codex_state_b64": out_state})

    async def tool_result(self, session_handle: str, tool_name: str, result: dict) -> None:
        state = self._session_state(session_handle)
        row = {"ts": _utc_now().isoformat(), "tool_name": tool_name, "result": result}
        state["tool_results"].append(row)
        log = self.events_dir / f"{session_handle}_tool_results.jsonl"
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
