from __future__ import annotations

import asyncio

from shared.proc_rpc import ProcClient


class TelegramGateRunner:
    def __init__(self) -> None:
        self.secrets = ProcClient("sheriff-secrets")
        self.policy = ProcClient("sheriff-policy")

    async def unlock(self, password: str) -> dict:
        _, resp = await self.secrets.request("secrets.unlock", {"password": password})
        return resp.get("result", {})

    async def apply_callback(self, approval_id: str, action: str) -> dict:
        _, resp = await self.policy.request("policy.apply_callback", {"approval_id": approval_id, "action": action})
        return resp.get("result", {})

    async def run_forever(self) -> None:
        while True:
            await asyncio.sleep(3600)
