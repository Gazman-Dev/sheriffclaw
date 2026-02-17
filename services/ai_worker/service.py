from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

from python_openclaw.worker.worker_main import Worker
from services.ai_worker.skill_loader import SkillLoader
from shared.paths import llm_root


class AIWorkerService:
    def __init__(self) -> None:
        workspace = llm_root() / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        self.worker = Worker()
        self.sessions: dict[str, list[dict[str, Any]]] = {}
        self.loader = SkillLoader(Path.cwd() / "skills")
        self.skills = self.loader.load()

    async def open_session(self, payload: dict, emit_event, req_id: str) -> dict:
        sid = payload.get("session_id") or str(uuid.uuid4())
        self.sessions[sid] = []
        return {"session_handle": sid}

    async def close_session(self, payload: dict, emit_event, req_id: str) -> dict:
        self.sessions.pop(payload["session_handle"], None)
        return {"status": "closed"}

    async def append_tool_result(self, payload: dict, emit_event, req_id: str) -> dict:
        sid = payload["session_handle"]
        tool_name = payload.get("tool_name", "tool")
        content = str(payload.get("result", {}))
        self.sessions.setdefault(sid, []).append({"role": "tool", "name": tool_name, "content": content})
        return {"status": "appended"}

    async def user_message(self, payload: dict, emit_event, req_id: str) -> dict:
        sid = payload["session_handle"]
        text = payload.get("text", "")
        if text:
            self.sessions.setdefault(sid, []).append({"role": "user", "content": text})
        async for event in self.worker.run(sid, self.sessions.get(sid, [])):
            await emit_event(event["stream"], event["payload"])
        return {"status": "done"}

    async def run_agent(self, payload: dict, emit_event, req_id: str) -> dict:
        sid = payload.get("session_id") or str(uuid.uuid4())
        msgs = payload.get("messages", [])
        self.sessions.setdefault(sid, []).extend(msgs)
        async for event in self.worker.run(sid, self.sessions[sid]):
            await emit_event(event["stream"], event["payload"])
        return {"status": "done", "session_id": sid}

    async def skills_list(self, payload: dict, emit_event, req_id: str) -> dict:
        self.skills = self.loader.load()
        return {"skills": sorted(self.skills.keys())}

    async def skill_run(self, payload: dict, emit_event, req_id: str) -> dict:
        name = payload["name"]
        module = self.skills.get(name)
        if not module:
            raise ValueError(f"unknown skill {name}")
        result = await module.run(payload.get("payload", {}), emit_event=emit_event)
        await emit_event("skill.result", {"name": name, "result": result})
        return {"name": name, "result": result}

    async def skill_main(self, payload: dict, emit_event, req_id: str) -> dict:
        argv = payload.get("argv", [])
        stdin = payload.get("stdin", "")
        name = argv[0] if argv else payload.get("name")
        module = self.skills.get(name)
        if not module:
            raise ValueError(f"unknown skill {name}")
        result = await module.run({"argv": argv[1:], "stdin": stdin}, emit_event=emit_event)
        return {"stdout": str(result), "stderr": "", "code": 0}

    def ops(self):
        return {
            "agent.run": self.run_agent,
            "agent.session.open": self.open_session,
            "agent.session.user_message": self.user_message,
            "agent.session.tool_result": self.append_tool_result,
            "agent.session.close": self.close_session,
            "skills.list": self.skills_list,
            "skill.run": self.skill_run,
            "skill.main": self.skill_main,
        }
