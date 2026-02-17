from __future__ import annotations

from collections.abc import AsyncIterator

from shared.proc_rpc import ProcClient


class IPCClient:
    def __init__(self, binary: str = "ai-worker") -> None:
        self.client = ProcClient(binary)

    async def run_agent(self, session_id: str, messages: list[dict]) -> AsyncIterator[dict]:
        stream, final = await self.client.request(
            "agent.run",
            {"session_id": session_id, "messages": messages},
            stream_events=True,
        )
        async for frame in stream:
            yield {"stream": frame["event"], "payload": frame.get("payload", {})}
        await final
