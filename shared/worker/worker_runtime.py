from __future__ import annotations

import uuid
from pathlib import Path

from shared.llm.providers import StubProvider
from shared.llm.registry import resolve_model
from shared.skills.loader import SkillLoader


class WorkerRuntime:
    def __init__(self):
        self.sessions: dict[str, list[dict]] = {}
        self.providers: dict[str, StubProvider] = {}
        self.skill_loader = SkillLoader(Path.cwd() / "skills")
        self.skills = self.skill_loader.load()

    def _provider(self, provider: str, api_key: str, base_url: str = "") -> StubProvider:
        key = f"{provider}:{api_key}:{base_url}"
        if key not in self.providers:
            self.providers[key] = StubProvider()
        return self.providers[key]

    async def session_open(self, session_id: str | None) -> str:
        handle = session_id or str(uuid.uuid4())
        self.sessions.setdefault(handle, [])
        return handle

    async def session_close(self, session_handle: str) -> None:
        self.sessions.pop(session_handle, None)

    async def user_message(self, session_handle: str, text: str, model_ref: str | None, emit_event):
        history = self.sessions.setdefault(session_handle, [])
        history.append({"role": "user", "content": text})
        lower = text.lower()
        if "tool" in lower:
            await emit_event("tool.call", {"tool_name": "tools.exec", "payload": {"argv": ["echo", "tool-invoked"], "taint": False}, "reason": "trigger word"})
        model = resolve_model(model_ref)
        provider = self._provider("stub", "", "")
        answer = await provider.generate(history, model=model)
        await emit_event("assistant.delta", {"text": answer})
        await emit_event("assistant.final", {"text": answer})
        history.append({"role": "assistant", "content": answer})

    async def tool_result(self, session_handle: str, tool_name: str, result: dict) -> None:
        self.sessions.setdefault(session_handle, []).append({"role": "tool", "name": tool_name, "content": str(result)})

    async def list_skills(self) -> list[str]:
        self.skills = self.skill_loader.load()
        return sorted(self.skills.keys())

    async def skill_run(self, name: str, payload: dict, emit_event) -> dict:
        self.skills = self.skill_loader.load()
        module = self.skills.get(name)
        if not module:
            raise ValueError(f"unknown skill: {name}")
        return await module.run(payload, emit_event=emit_event)
