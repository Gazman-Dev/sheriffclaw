from __future__ import annotations

from collections.abc import AsyncIterator

from python_openclaw.worker.agent_stub import run_agent


class Worker:
    async def run(self, session_id: str, messages: list[dict]) -> AsyncIterator[dict]:
        async for event in run_agent(messages):
            yield event
