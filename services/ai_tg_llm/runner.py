from __future__ import annotations

import asyncio

from shared.proc_rpc import ProcClient


class TelegramLLMRunner:
    def __init__(self) -> None:
        self.gateway = ProcClient("sheriff-gateway")

    async def handle_text(self, user_id: str, text: str) -> list[dict]:
        events = []
        stream, final = await self.gateway.request(
            "gateway.handle_user_message",
            {"channel": "telegram_dm", "context": {"user_id": user_id}, "principal_external_id": str(user_id), "text": text},
            stream_events=True,
        )
        async for frame in stream:
            events.append(frame)
        await final
        return events

    async def run_forever(self) -> None:
        while True:
            await asyncio.sleep(3600)
