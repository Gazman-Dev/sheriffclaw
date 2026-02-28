from __future__ import annotations

# Retained for back-compat with tests, but deprecated under code-first paradigm.
from typing import Protocol


class SkillModule(Protocol):
    SKILL_NAME: str

    async def run(self, payload: dict, *, emit_event): ...
