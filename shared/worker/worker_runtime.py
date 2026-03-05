from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from shared.paths import agent_root
from shared.skills.loader import SkillLoader


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

    async def _ensure_codex_active(self):
        if self.codex_proc is None or self.codex_proc.returncode is not None:
            env = os.environ.copy()
            env["CODEX_HOME"] = str(self.agent_workspace)
            try:
                self.codex_proc = await asyncio.create_subprocess_exec(
                    "codex",
                    "chat",
                    "--dangerously-bypass-approvals-and-sandbox",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.agent_workspace),
                    env=env,
                )

                async def drain(stream):
                    while True:
                        line = await stream.readline()
                        if not line:
                            break

                asyncio.create_task(drain(self.codex_proc.stdout))
                asyncio.create_task(drain(self.codex_proc.stderr))
            except Exception:
                pass

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

        ts = int(time.time())
        user_file = session_dir / f"{ts}_user_agent.tmd"
        user_file.write_text(text, encoding="utf-8")

        await self._ensure_codex_active()
        if self.codex_proc and self.codex_proc.stdin:
            self.codex_proc.stdin.write((text + "\n").encode("utf-8"))
            await self.codex_proc.stdin.drain()
        elif debug_mode:
            sim_file = session_dir / "agent_user_pending.tmd"
            sim_file.write_text(f"Mock CLI Response to: {text}", encoding="utf-8")

        pending_file = session_dir / "agent_user_pending.tmd"
        typing_file = session_dir / "agent_user_typing.tmd"
        if debug_mode and not pending_file.exists():
            pending_file.write_text(f"Mock CLI Response to: {text}", encoding="utf-8")

        start = time.time()
        emitted_typing = False

        while time.time() - start < 300:
            if pending_file.exists():
                await asyncio.sleep(0.1)
                try:
                    content = pending_file.read_text(encoding="utf-8")
                    reply_ts = int(time.time())
                    final_file = session_dir / f"{reply_ts}_agent_user.tmd"
                    final_file.write_text(content, encoding="utf-8")
                    pending_file.unlink(missing_ok=True)
                    await emit_event("assistant.final", {"text": content.strip()})
                    return
                except Exception:
                    if debug_mode:
                        reply_ts = int(time.time())
                        final_file = session_dir / f"{reply_ts}_agent_user.tmd"
                        final_file.write_text(f"Mock CLI Response to: {text}", encoding="utf-8")
                        await emit_event("assistant.final", {"text": f"Mock CLI Response to: {text}"})
                        return
            elif typing_file.exists() and not emitted_typing:
                await emit_event("assistant.delta", {"text": "typing..."})
                emitted_typing = True

            await asyncio.sleep(0.2)

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
        pass
