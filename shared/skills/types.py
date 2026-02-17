from __future__ import annotations

from typing import Protocol


class SkillModule(Protocol):
    SKILL_NAME: str

    async def run(self, payload: dict, *, emit_event): ...
