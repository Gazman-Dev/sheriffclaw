from __future__ import annotations

from collections.abc import AsyncIterator

from python_openclaw.worker.worker_main import Worker


class IPCClient:
    def __init__(self, worker: Worker | None = None) -> None:
        self.worker = worker or Worker()

    async def run_agent(self, session_id: str, messages: list[dict]) -> AsyncIterator[dict]:
        async for event in self.worker.run(session_id, messages):
            yield event
