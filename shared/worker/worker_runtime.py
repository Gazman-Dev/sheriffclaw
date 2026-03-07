from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
from pathlib import Path

if os.name != "nt":
    import pty

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
            if hasattr(stream, "read_chunk"):
                chunk = await stream.read_chunk(512)
            else:
                chunk = await stream.read(512)
            if not chunk:
                return
            text = chunk.decode("utf-8", errors="replace")
            sink.append(text)
            if stream_name == "stdout":
                await self._handle_codex_stdout(text)

    async def _write_codex_bytes(self, payload: bytes) -> None:
        if self.codex_proc is None:
            raise RuntimeError("codex process is not running")
        if hasattr(self.codex_proc, "write_stdin"):
            await self.codex_proc.write_stdin(payload)
            return
        if getattr(self.codex_proc, "stdin", None) is None:
            raise RuntimeError("codex stdin unavailable")
        self.codex_proc.stdin.write(payload)
        await self.codex_proc.stdin.drain()

    async def _write_codex_control(self, payload: bytes, *, reason: str, session: str | None = None) -> None:
        if self.codex_proc is None:
            self._debug_log("codex_control_unavailable", reason=reason, session=session)
            return
        try:
            await self._write_codex_bytes(payload)
            self._debug_log("codex_control_write", reason=reason, session=session, payload_hex=payload.hex())
        except Exception as exc:
            self._debug_log("codex_control_write_failed", reason=reason, session=session, error=str(exc))

    def _prompt_session(self) -> str:
        return self.active_session_handle or "primary_session"

    def _extract_prompt_lines(self, text: str) -> list[str]:
        normalized = self._normalized_codex_text(text)
        lines = [line.strip() for line in normalized.splitlines()]
        lines = [line for line in lines if line]
        return lines[-40:]

    def _build_manual_prompt(self, text: str) -> dict | None:
        lines = self._extract_prompt_lines(text)
        context_lines, options = self._extract_interactive_menu(lines)
        if options:
            return {
                "key": f"generic_menu:{'|'.join(opt['label'] for opt in options)}",
                "message": "Codex is waiting on an interactive selection.",
                "details": "\n".join(context_lines),
                "options": options,
            }
        return None

    def _extract_interactive_menu(self, lines: list[str]) -> tuple[list[str], list[dict]]:
        candidate_starts = [
            idx
            for idx, line in enumerate(lines)
            if any(token in line for token in ("choose", "select", "press enter to confirm", "use ↑/↓", "use up/down"))
        ]
        for idx in reversed(candidate_starts):
            start = max(idx - 4, 0)
            end = min(idx + 8, len(lines))
            window = lines[start:end]
            options = self._extract_menu_options(window)
            if options:
                return window, options

        menu_indices = [idx for idx, line in enumerate(lines) if re.match(r"^[>\s]*([0-9]+)[.)]\s+(.+)$", line)]
        if not menu_indices:
            return [], []
        groups: list[list[int]] = []
        current = [menu_indices[0]]
        for idx in menu_indices[1:]:
            if idx == current[-1] + 1:
                current.append(idx)
            else:
                groups.append(current)
                current = [idx]
        groups.append(current)
        last_group = groups[-1]
        start = max(last_group[0] - 3, 0)
        end = min(last_group[-1] + 4, len(lines))
        window = lines[start:end]
        return window, self._extract_menu_options(window)

    def _extract_menu_options(self, lines: list[str]) -> list[dict]:
        options: list[dict] = []
        seen_labels: set[str] = set()
        for line in lines:
            match = re.match(r"^[>\s]*([0-9]+)[.)]\s+(.+)$", line)
            if not match:
                continue
            idx = int(match.group(1))
            label = match.group(2).strip()
            if (
                not label
                or label in seen_labels
                or idx <= 0
                or label.startswith("/")
                or label.startswith("http")
                or label.startswith("/users/")
            ):
                continue
            seen_labels.add(label)
            payload = (b"\r" if idx == 1 else (b"\x1b[B" * (idx - 1)) + b"\r")
            options.append({"label": label, "payload": payload})
        return options

    async def _publish_manual_prompt(self, prompt: dict) -> None:
        session = self._prompt_session()
        existing = self.codex_prompt_state.get(session)
        if existing and existing.get("key") == prompt["key"]:
            return
        self.codex_prompt_state[session] = prompt
        session_dir = self.conversations_dir / session
        session_dir.mkdir(parents=True, exist_ok=True)
        pending_file = session_dir / "agent_user_pending.tmd"
        body = self._render_prompt_text(prompt)
        pending_file.write_text(body, encoding="utf-8")
        self._debug_log(
            "codex_prompt_waiting_for_user",
            session=session,
            key=prompt["key"],
            options=[f"/option{i + 1} - {opt['label']}" for i, opt in enumerate(prompt["options"])],
        )

    def _render_prompt_text(self, prompt: dict) -> str:
        option_lines = [f"/option{i + 1} - {opt['label']}" for i, opt in enumerate(prompt["options"])]
        body = prompt["message"]
        if prompt.get("details"):
            body += f"\n\n{prompt['details']}"
        body += "\n\nChoose one:\n" + "\n".join(option_lines)
        return body

    def _normalized_codex_text(self, text: str) -> str:
        stripped = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
        stripped = re.sub(r"\x1b[@-_]", "", stripped)
        stripped = stripped.replace("\r", "\n")
        return stripped.lower()

    async def _handle_codex_stdout(self, text: str) -> None:
        self.codex_prompt_buffer = (self.codex_prompt_buffer + text)[-8000:]
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
                if os.name != "nt" and not debug_enabled():
                    self.codex_proc = _PosixPtyProcess.start(cmd, cwd=str(self.agent_workspace), env=env)
                else:
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
                if isinstance(self.codex_proc, _PosixPtyProcess):
                    self.codex_stdout_task = asyncio.create_task(
                        self._drain_codex_stream(self.codex_proc, self.codex_stdout_log, "stdout")
                    )
                elif use_pipe_logs and self.codex_proc.stdout is not None and self.codex_proc.stderr is not None:
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
        if self.codex_proc is None:
            self._debug_log("codex_stdin_unavailable", session=session_handle)
            return
        payload = (text.rstrip("\n") + "\n").encode("utf-8")
        try:
            await self._write_codex_bytes(payload)
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
        if session_handle in self.codex_prompt_state:
            await emit_event("assistant.final", {"text": self._render_prompt_text(self.codex_prompt_state[session_handle]).strip()})
            return
        debug_mode = os.environ.get("SHERIFF_DEBUG", "0") == "1"
        pending_file = session_dir / "agent_user_pending.tmd"
        typing_file = session_dir / "agent_user_typing.tmd"

        if session_handle not in self.codex_prompt_state:
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
            if session_handle in self.codex_prompt_state and pending_file.exists():
                content = pending_file.read_text(encoding="utf-8")
                self._debug_log("assistant_prompt", session=session_handle, text=content)
                await emit_event("assistant.final", {"text": content.strip()})
                return
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


class _PosixPtyProcess:
    def __init__(self, proc: subprocess.Popen[bytes], master_fd: int):
        self._proc = proc
        self._master_fd = master_fd

    @classmethod
    def start(cls, argv: list[str], *, cwd: str, env: dict[str, str]) -> "_PosixPtyProcess":
        master_fd, slave_fd = pty.openpty()
        try:
            proc = subprocess.Popen(
                argv,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=cwd,
                env=env,
                close_fds=True,
            )
        finally:
            os.close(slave_fd)
        return cls(proc, master_fd)

    @property
    def returncode(self):
        return self._proc.poll()

    async def read_chunk(self, size: int) -> bytes:
        try:
            return await asyncio.to_thread(os.read, self._master_fd, size)
        except OSError:
            return b""

    async def write_stdin(self, payload: bytes) -> None:
        await asyncio.to_thread(os.write, self._master_fd, payload)

    def terminate(self) -> None:
        self._proc.terminate()

    def kill(self) -> None:
        self._proc.kill()

    async def wait(self) -> int:
        try:
            return await asyncio.to_thread(self._proc.wait)
        finally:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
