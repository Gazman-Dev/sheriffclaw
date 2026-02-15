from __future__ import annotations

from dataclasses import dataclass

from python_openclaw.channels.protocol import ChannelContent, InboundEvent
from python_openclaw.gateway.core import GatewayCore
from python_openclaw.gateway.sessions import IdentityManager


@dataclass
class TelegramLLMBotAdapter:
    gateway: GatewayCore
    identities: IdentityManager
    bot_client: object

    async def on_message(self, user_id: int, chat_id: int, text: str, message_thread_id: int | None = None) -> None:
        if not self.identities.is_llm_user_allowed(user_id):
            await self.bot_client.send_message(chat_id, "Access denied")
            return
        principal = self.identities.principal_for("telegram", str(user_id))
        if principal is None:
            await self.bot_client.send_message(chat_id, "Identity not bound")
            return
        context = {"user_id": user_id}
        channel = "telegram_dm"
        if message_thread_id is not None:
            channel = "telegram_topic"
            context = {"chat_id": chat_id, "thread_id": message_thread_id}
        await self.gateway.handle_user_message(
            channel=channel,
            context=context,
            principal=principal,
            text=text,
            adapter=self,
        )

    async def send_message(self, session_key: str, content: ChannelContent) -> None:
        if content.image_url or content.image_base64:
            await self.bot_client.send_photo(session_key, content.image_url or content.image_base64)
            return
        if content.file_url:
            await self.bot_client.send_document(session_key, content.file_url)
            return
        await self.bot_client.send_message_stream(session_key, content.text or "")

    async def send_stream(self, session_key: str, event: dict) -> None:
        payload = event["payload"]
        if event["stream"] == "assistant.delta":
            await self.send_message(session_key, ChannelContent(text=payload["delta"]))
        elif event["stream"] == "assistant.final":
            await self.send_message(session_key, ChannelContent(text=payload["content"]))
        elif event["stream"] == "tool.result" and payload.get("status") == "approval_required":
            summary = payload["summary"]
            await self.send_message(
                session_key,
                ChannelContent(text=f"Approval required for {summary['method']} {summary['host']}{summary['path']}"),
            )

    async def send_approval_request(self, approval_id: str, context: dict) -> None:
        session_key = context.get("session_key", "")
        await self.bot_client.send_approval(session_key, approval_id, context)

    def parse_inbound(self, raw_payload: dict) -> InboundEvent:
        if "callback_query" in raw_payload:
            cb = raw_payload["callback_query"]
            msg = cb.get("message", {})
            chat = msg.get("chat", {})
            thread_id = msg.get("message_thread_id")
            skey = f"tg:{chat.get('id')}:{thread_id or 'dm'}"
            return InboundEvent(
                principal_external_id=str(cb.get("from", {}).get("id", "")),
                channel="telegram_callback",
                session_key=skey,
                callback_data={"data": cb.get("data"), "id": cb.get("id")},
                raw_payload=raw_payload,
            )

        msg = raw_payload.get("message", {})
        chat = msg.get("chat", {})
        thread_id = msg.get("message_thread_id")
        if thread_id is not None:
            skey = f"tg:group:{chat.get('id')}:{thread_id}"
        else:
            skey = f"tg:dm:{msg.get('from', {}).get('id')}"
        return InboundEvent(
            principal_external_id=str(msg.get("from", {}).get("id", "")),
            channel="telegram",
            session_key=skey,
            text=msg.get("text"),
            raw_payload=raw_payload,
        )
