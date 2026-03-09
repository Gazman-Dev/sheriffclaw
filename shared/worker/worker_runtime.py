from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from shared.codex_output import extract_text_content
from shared.codex_session_manager import CodexSessionManager
from shared.paths import agent_repo_root
from shared.skills.loader import SkillLoader


class WorkerRuntime:
    def __init__(self, *, session_manager: CodexSessionManager | None = None):
        self.repo_root = Path(__file__).resolve().parents[2]
        self.agent_repo = agent_repo_root()
        self.session_manager = session_manager or CodexSessionManager()
        self.skill_loader = SkillLoader(
            user_root=self.agent_repo / "skills",
            system_root=self.repo_root / "skills",
        )
        self.skills = self.skill_loader.load()

    async def session_open(self, session_id: str | None) -> str:
        session_key = str(session_id or "private_main")
        await self.session_manager.ensure_session(session_key, hydrate=False)
        return session_key

    async def session_close(self, session_handle: str) -> None:
        await self.session_manager.invalidate_session(session_handle, reason="close")

    async def user_message(
        self,
        session_handle: str,
        text: str,
        model_ref: str | None,
        emit_event,
        **kwargs: Any,
    ) -> None:
        result = await self.session_manager.send_message(session_handle, text)
        content = extract_text_content(result.get("result") or {})
        if content:
            await emit_event("assistant.final", {"text": str(content)})

    async def tool_result(self, session_handle: str, tool_name: str, result: dict[str, Any]) -> None:
        # Tool feedback is no longer pushed back into a terminal chat loop.
        # Keep the method as a no-op while callers are migrated.
        return None

    async def list_skills(self) -> list[dict[str, Any]]:
        return [
            {
                "name": skill.name,
                "description": skill.description,
                "command": skill.command,
                "tags": skill.tags,
                "source": skill.source,
            }
            for skill in sorted(self.skills.values(), key=lambda item: item.name)
        ]

    async def skill_run(self, name: str, payload: dict[str, Any], emit_event) -> dict[str, Any]:
        skill = self.skills.get(name)
        if skill is None:
            raise ValueError(f"unknown skill: {name}")

        run_py = skill.root / "run.py"
        if run_py.exists():
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(run_py),
                cwd=str(skill.root),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdin_data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            stdout, stderr = await proc.communicate(stdin_data)
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "code": proc.returncode,
            }

        completed = await asyncio.to_thread(
            subprocess.run,
            skill.command,
            cwd=str(skill.root),
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "code": completed.returncode,
        }
