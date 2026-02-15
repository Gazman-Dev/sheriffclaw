from __future__ import annotations

from dataclasses import dataclass

from python_openclaw.gateway.core import GatewayCore
from python_openclaw.gateway.sessions import IdentityManager


@dataclass
class TelegramLLMBotAdapter:
    gateway: GatewayCore
    identities: IdentityManager
    bot_client: object

    async def on_message(self, user_id: int, chat_id: int, text: str) -> None:
        if not self.identities.is_llm_user_allowed(user_id):
            await self.bot_client.send_message(chat_id, "Access denied")
            return
        principal = self.identities.principal_for("telegram", str(user_id))
        if principal is None:
            await self.bot_client.send_message(chat_id, "Identity not bound")
            return
        await self.gateway.handle_user_message(
            channel="telegram_dm",
            context={"user_id": user_id},
            principal=principal,
            text=text,
            adapter=self,
        )

    async def send_stream(self, session_key: str, event: dict) -> None:
        payload = event["payload"]
        if event["stream"] == "assistant.delta":
            await self.bot_client.send_message_stream(session_key, payload["delta"])
        elif event["stream"] == "assistant.final":
            await self.bot_client.send_message_stream(session_key, payload["content"])
        elif event["stream"] == "tool.result" and payload.get("status") == "approval_required":
            summary = payload["summary"]
            await self.bot_client.send_message_stream(
                session_key,
                f"Approval required for {summary['method']} {summary['host']}{summary['path']}",
            )
