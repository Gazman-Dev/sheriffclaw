from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path

from shared.oplog import RotatingTextLog
from shared.paths import agent_root, llm_root
from shared.skills.loader import SkillLoader
from shared.worker.codex_cli import augment_path, build_chat_command, debug_enabled, resolve_codex_binary


class WorkerRuntime:
    def __init__(self):
        self.repo_root = Path(__file__).resolve().parents[2]
        self.agent_workspace = agent_root()
        self.agent_workspace.mkdir(parents=True, exist_ok=True)

        self.conversations_dir = self.agent_workspace / "conversations" / "sessions"
        self.conversations_dir.mkdir(parents=True, exist_ok=True)

        (self.agent_workspace / "skill").mkdir(parents=True, exist_ok=True)
        self.skill_loader = SkillLoader(
            user_root=self.agent_workspace / "skill",
            system_root=None,
        )
        self.skills = self.skill_loader.load()
        self.codex_proc = None
        self.codex_start_error = ""
        self.debug_log_path = llm_root() / "state" / "debug" / "worker_runtime.jsonl"
        self.codex_stdout_task = None
        self.codex_stderr_task = None
        self.codex_stdout_log = RotatingTextLog(llm_root() / "logs" / "codex.out")
        self.codex_stderr_log = RotatingTextLog(llm_root() / "logs" / "codex.err")
        self.codex_prompt_buffer = ""
        self.codex_prompt_last_action: dict[str, float] = {}
        self.codex_prompt_state: dict[str, dict] = {}
        self.active_session_handle = "primary_session"

    def _debug_log(self, event: str, **payload) -> None:
        self.debug_log_path.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": time.time(), "event": event, **payload}
        with self.debug_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    async def _drain_codex_stream(self, stream, sink: RotatingTextLog, stream_name: str) -> None:
        while True:
            chunk = await stream.read(512)
            if not chunk:
                return
            text = chunk.decode("utf-8", errors="replace")
            sink.append(text)
            if stream_name == "stdout":
                await self._handle_codex_stdout(text)

    async def _write_codex_control(self, payload: bytes, *, reason: str, session: str | None = None) -> None:
        if self.codex_proc is None or self.codex_proc.stdin is None:
            self._debug_log("codex_control_unavailable", reason=reason, session=session)
            return
        try:
            self.codex_proc.stdin.write(payload)
            await self.codex_proc.stdin.drain()
            self._debug_log("codex_control_write", reason=reason, session=session, payload_hex=payload.hex())
        except Exception as exc:
            self._debug_log("codex_control_write_failed", reason=reason, session=session, error=str(exc))

    def _prompt_session(self) -> str:
        return self.active_session_handle or "primary_session"

    def _extract_prompt_lines(self, text: str) -> list[str]:
        normalized = self._normalized_codex_text(text)
        lines = [line.strip() for line in normalized.splitlines()]
        lines = [line for line in lines if line]
        return lines[-12:]

    def _build_manual_prompt(self, text: str) -> dict | None:
        lines = self._extract_prompt_lines(text)
        joined = "\n".join(lines)
        if "trust the current folder" in joined:
            return {
                "key": "trust_folder_manual",
                "message": "Codex is asking whether to trust the current folder.",
                "details": joined,
                "options": [
                    {"label": "Trust once", "payload": b"\r"},
                    {"label": "Always trust", "payload": b"\x1b[B\r"},
                ],
            }
        if "update to the latest version" in joined or "would you like to update" in joined:
            return {
                "key": "update_manual",
                "message": "Codex is asking whether to update itself.",
                "details": joined,
                "options": [
                    {"label": "Update", "payload": b"\r"},
                    {"label": "Skip update", "payload": b"\x1b[B\r"},
                ],
            }
        if "trust" in joined or "update" in joined:
            return {
                "key": "generic_prompt",
                "message": "Codex is waiting on an interactive prompt.",
                "details": joined,
                "options": [{"label": "Accept default", "payload": b"\r"}],
            }
        return None

    async def _publish_manual_prompt(self, prompt: dict) -> None:
        session = self._prompt_session()
        existing = self.codex_prompt_state.get(session)
        if existing and existing.get("key") == prompt["key"]:
            return
        self.codex_prompt_state[session] = prompt
        session_dir = self.conversations_dir / session
        session_dir.mkdir(parents=True, exist_ok=True)
        pending_file = session_dir / "agent_user_pending.tmd"
        option_lines = [f"/option{i + 1} - {opt['label']}" for i, opt in enumerate(prompt["options"])]
        body = prompt["message"]
        if prompt.get("details"):
            body += f"\n\n{prompt['details']}"
        body += "\n\nChoose one:\n" + "\n".join(option_lines)
        pending_file.write_text(body, encoding="utf-8")
        self._debug_log("codex_prompt_waiting_for_user", session=session, key=prompt["key"], options=option_lines)

    def _normalized_codex_text(self, text: str) -> str:
        stripped = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
        stripped = re.sub(r"\x1b[@-_]", "", stripped)
        stripped = stripped.replace("\r", "\n")
        return stripped.lower()

    def _prompt_actions_for_text(self, text: str) -> list[tuple[str, bytes]]:
        normalized = self._normalized_codex_text(text)
        actions: list[tuple[str, bytes]] = []
        if (
            "update to the latest version" in normalized
            and "skip update" in normalized
            and "update now" in normalized
        ) or (
            "would you like to update" in normalized
            and "not now" in normalized
            and "update" in normalized
        ):
            actions.append(("accept_update", b"\r"))
        if (
            "trust the current folder" in normalized
            and "always trust" in normalized
            and ("trust once" in normalized or "this time" in normalized)
        ):
            actions.append(("always_trust_folder", b"\x1b[B\r"))
        return actions

    async def _handle_codex_stdout(self, text: str) -> None:
        self.codex_prompt_buffer = (self.codex_prompt_buffer + text)[-8000:]
        now = time.time()
        actions = self._prompt_actions_for_text(self.codex_prompt_buffer)
        for reason, payload in actions:
            if now - self.codex_prompt_last_action.get(reason, 0.0) < 2.0:
                continue
            self.codex_prompt_last_action[reason] = now
            await self._write_codex_control(payload, reason=reason)
            self.codex_prompt_state.pop(self._prompt_session(), None)
        if not actions:
            prompt = self._build_manual_prompt(self.codex_prompt_buffer)
            if prompt is not None:
                await self._publish_manual_prompt(prompt)

    async def _ensure_codex_active(self):
        if self.codex_proc is None or self.codex_proc.returncode is not None:
            env = os.environ.copy()
            env["CODEX_HOME"] = str(self.agent_workspace)
            env["PATH"] = augment_path(env.get("PATH"))
            cmd = build_chat_command(self.repo_root)
            use_pipe_logs = os.name != "nt"
            try:
                self.codex_proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE if use_pipe_logs else asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE if use_pipe_logs else asyncio.subprocess.DEVNULL,
                    cwd=str(self.agent_workspace),
                    env=env,
                )
                self.codex_start_error = ""
                self.codex_prompt_buffer = ""
                self.codex_prompt_last_action.clear()
                if use_pipe_logs and self.codex_proc.stdout is not None and self.codex_proc.stderr is not None:
                    self.codex_stdout_task = asyncio.create_task(
                        self._drain_codex_stream(self.codex_proc.stdout, self.codex_stdout_log, "stdout")
                    )
                    self.codex_stderr_task = asyncio.create_task(
                        self._drain_codex_stream(self.codex_proc.stderr, self.codex_stderr_log, "stderr")
                    )
                self._debug_log(
                    "codex_launch",
                    command=cmd,
                    cwd=str(self.agent_workspace),
                    resolved_binary=resolve_codex_binary(),
                    path=env.get("PATH", ""),
                    stdout_log=str(llm_root() / "logs" / "codex.out"),
                    stderr_log=str(llm_root() / "logs" / "codex.err"),
                )
            except Exception as exc:
                self.codex_proc = None
                self.codex_start_error = str(exc)
                self._debug_log(
                    "codex_launch_failed",
                    command=cmd,
                    resolved_binary=resolve_codex_binary(),
                    path=env.get("PATH", ""),
                    error=self.codex_start_error,
                )
                await self._close_codex_logs()

    async def _send_codex_stdin(self, text: str, session_handle: str) -> None:
        if self.codex_proc is None or self.codex_proc.stdin is None:
            self._debug_log("codex_stdin_unavailable", session=session_handle)
            return
        payload = (text.rstrip("\n") + "\n").encode("utf-8")
        try:
            self.codex_proc.stdin.write(payload)
            await self.codex_proc.stdin.drain()
            self._debug_log("codex_stdin_write", session=session_handle, bytes=len(payload), text=text)
        except Exception as exc:
            self._debug_log("codex_stdin_write_failed", session=session_handle, error=str(exc))

    async def _handle_prompt_selection(self, session_handle: str, text: str, emit_event) -> bool:
        if not text.startswith("/option"):
            return False
        state = self.codex_prompt_state.get(session_handle)
        if not state:
            await emit_event("assistant.final", {"text": "No pending Codex prompt is waiting for a selection."})
            return True
        suffix = text[len("/option") :].strip()
        try:
            idx = int(suffix) - 1
        except ValueError:
            idx = -1
        if idx < 0 or idx >= len(state["options"]):
            allowed = ", ".join(f"/option{i + 1}" for i in range(len(state["options"])))
            await emit_event("assistant.final", {"text": f"Invalid selection. Available choices: {allowed}"})
            return True
        choice = state["options"][idx]
        await self._write_codex_control(choice["payload"], reason=f"user_{text}", session=session_handle)
        self.codex_prompt_state.pop(session_handle, None)
        await emit_event("assistant.final", {"text": f"Sent {text} to Codex."})
        return True

    async def user_message(
        self,
        session_handle: str,
        text: str,
        model_ref: str | None,
        emit_event,
        **kwargs,
    ):
        session_dir = self.conversations_dir / session_handle
        session_dir.mkdir(parents=True, exist_ok=True)
        self.active_session_handle = session_handle
        if await self._handle_prompt_selection(session_handle, text.strip(), emit_event):
            return
        debug_mode = os.environ.get("SHERIFF_DEBUG", "0") == "1"
        pending_file = session_dir / "agent_user_pending.tmd"
        typing_file = session_dir / "agent_user_typing.tmd"

        for stale in (pending_file, typing_file):
            if stale.exists():
                stale.unlink(missing_ok=True)
                self._debug_log("stale_file_removed", session=session_handle, file=stale.name)

        await self._ensure_codex_active()
        if self.codex_start_error:
            await emit_event("assistant.final", {"text": f"Codex background process failed to start: {self.codex_start_error}"})
            return

        ts = int(time.time())
        user_file = session_dir / f"{ts}_user_agent.tmd"
        user_file.write_text(text, encoding="utf-8")
        self._debug_log("user_message", session=session_handle, file=user_file.name, text=text)
        await self._send_codex_stdin(text, session_handle)

        start = time.time()
        emitted_typing = False
        timeout_sec = 300.0
        if debug_mode:
            try:
                timeout_sec = float(os.environ.get("SHERIFF_DEBUG_TIMEOUT_SEC", timeout_sec))
            except ValueError:
                timeout_sec = 300.0

        while time.time() - start < timeout_sec:
            if pending_file.exists():
                await asyncio.sleep(0.1)
                try:
                    content = pending_file.read_text(encoding="utf-8")
                    reply_ts = int(time.time())
                    final_file = session_dir / f"{reply_ts}_agent_user.tmd"
                    final_file.write_text(content, encoding="utf-8")
                    pending_file.unlink(missing_ok=True)
                    typing_file.unlink(missing_ok=True)
                    self._debug_log("assistant_final", session=session_handle, file=final_file.name, text=content.strip())
                    await emit_event("assistant.final", {"text": content.strip()})
                    return
                except Exception:
                    self._debug_log("pending_read_failed", session=session_handle)
            elif typing_file.exists() and not emitted_typing:
                self._debug_log("assistant_typing", session=session_handle)
                await emit_event("assistant.delta", {"text": "typing..."})
                emitted_typing = True

            await asyncio.sleep(0.2)

        self._debug_log("assistant_timeout", session=session_handle, timeout_sec=timeout_sec)
        await emit_event("assistant.final", {"text": "Agent background process response timed out."})

    async def tool_result(self, session_handle: str, tool_name: str, result: dict) -> None:
        session_dir = self.conversations_dir / session_handle
        session_dir.mkdir(parents=True, exist_ok=True)

        row = {"ts": int(time.time()), "tool_name": tool_name, "result": result}
        log_file = session_dir / "tool_results.jsonl"
        with log_file.open("a", encoding="utf-8") as fh:
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

    async def session_open(self, session_id: str | None) -> str:
        return session_id or "primary_session"

    async def session_close(self, session_handle: str) -> None:
        if self.codex_proc is not None and self.codex_proc.returncode is None:
            self.codex_proc.terminate()
            try:
                await asyncio.wait_for(self.codex_proc.wait(), timeout=2.0)
            except Exception:
                self.codex_proc.kill()
                await self.codex_proc.wait()
        self.codex_proc = None
        await self._close_codex_logs()

    async def _close_codex_logs(self) -> None:
        for task_name in ("codex_stdout_task", "codex_stderr_task"):
            task = getattr(self, task_name, None)
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
                setattr(self, task_name, None)
