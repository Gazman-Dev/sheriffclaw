from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from shared.oplog import get_rotating_logger
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
        self.codex_stdout_logger = get_rotating_logger("codex.stdout", llm_root() / "logs" / "codex.out")
        self.codex_stderr_logger = get_rotating_logger("codex.stderr", llm_root() / "logs" / "codex.err")

    def _debug_log(self, event: str, **payload) -> None:
        self.debug_log_path.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": time.time(), "event": event, **payload}
        with self.debug_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    async def _drain_codex_stream(self, stream, logger) -> None:
        while True:
            line = await stream.readline()
            if not line:
                return
            logger.info("%s", line.decode("utf-8", errors="replace").rstrip())

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
                if use_pipe_logs and self.codex_proc.stdout is not None and self.codex_proc.stderr is not None:
                    self.codex_stdout_task = asyncio.create_task(
                        self._drain_codex_stream(self.codex_proc.stdout, self.codex_stdout_logger)
                    )
                    self.codex_stderr_task = asyncio.create_task(
                        self._drain_codex_stream(self.codex_proc.stderr, self.codex_stderr_logger)
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
