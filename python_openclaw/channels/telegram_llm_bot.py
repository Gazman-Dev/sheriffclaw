from __future__ import annotations

from dataclasses import dataclass

from python_openclaw.channels.protocol import ChannelContent, InboundEvent
from python_openclaw.gateway.core import GatewayCore
from python_openclaw.gateway.sessions import IdentityManager


def markdown_to_telegram_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dataclass
class TelegramLLMBotClient:
    bot: object

    async def send_message(self, chat_id: int, text: str) -> None:
        await self.bot.send_message(chat_id, text)

    async def send_message_stream(self, session_key: str, text: str) -> None:
        chat_id = int(session_key.split(":")[-1]) if session_key.startswith("tg:dm:") else session_key
        await self.bot.send_message(chat_id, text)

    async def send_photo(self, session_key: str, payload: str) -> None:
        chat_id = int(session_key.split(":")[-1]) if session_key.startswith("tg:dm:") else session_key
        await self.bot.send_photo(chat_id, payload)

    async def send_document(self, session_key: str, payload: str) -> None:
        chat_id = int(session_key.split(":")[-1]) if session_key.startswith("tg:dm:") else session_key
        await self.bot.send_document(chat_id, payload)

    async def send_approval(self, session_key: str, approval_id: str, summary: dict) -> None:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        chat_id = int(session_key.split(":")[-1]) if str(session_key).startswith("tg:dm:") else session_key
        text = (
            f"Permission request: {summary.get('resource_type')}={summary.get('resource_value')}\n"
            f"Principal: {summary.get('principal')}"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Approve Once", callback_data=f"approval:{approval_id}:allow_once"),
                    InlineKeyboardButton(text="Always Allow", callback_data=f"approval:{approval_id}:always_allow"),
                    InlineKeyboardButton(text="Deny", callback_data=f"approval:{approval_id}:deny"),
                ]
            ]
        )
        await self.bot.send_message(chat_id, text, reply_markup=kb)


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
        await self.bot_client.send_message_stream(session_key, markdown_to_telegram_html(content.text or ""))

    async def send_stream(self, session_key: str, event: dict) -> None:
        payload = event["payload"]
        if event["stream"] == "assistant.delta":
            await self.send_message(session_key, ChannelContent(text=payload["delta"]))
        elif event["stream"] == "assistant.final":
            if payload.get("image_url") or payload.get("image_base64"):
                await self.send_message(
                    session_key,
                    ChannelContent(
                        text=payload.get("content"),
                        image_url=payload.get("image_url"),
                        image_base64=payload.get("image_base64"),
                    ),
                )
            else:
                await self.send_message(session_key, ChannelContent(text=payload.get("content", "")))
        elif event["stream"] == "tool.result" and payload.get("status") in {"approval_required", "approval_requested"}:
            await self.send_message(session_key, ChannelContent(text="Approval workflow triggered in Gate bot."))
        elif event["stream"] == "tool.result" and payload.get("status") == "permission_denied":
            resource = payload.get("resource", {})
            await self.send_message(
                session_key,
                ChannelContent(text=f"Gate denied access to {resource.get('type')}={resource.get('value')} (403)."),
            )

    async def send_approval_request(self, approval_id: str, context: dict) -> None:
        session_key = context.get("session_key", "")
        await self.bot_client.send_approval(session_key, approval_id, context)


    async def on_approval_callback(self, approval_id: str, chat_id: int, action: str | None = None) -> None:
        if not action:
            await self.bot_client.send_message(chat_id, "Missing action")
            return
        prompt = self.gateway.approval_gate.apply_callback(approval_id, action)
        if not prompt:
            await self.bot_client.send_message(chat_id, "Approval request not found")
            return
        await self.bot_client.send_message(chat_id, f"Recorded {action} for {prompt.resource_type}:{prompt.resource_value}")

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


class TelegramLLMBotRunner:
    def __init__(self, adapter: TelegramLLMBotAdapter, bot: object):
        self.adapter = adapter
        self.bot = bot

    async def run_polling(self) -> None:
        try:
            from aiogram import Dispatcher, F
            from aiogram.filters import CommandStart
            from aiogram.types import CallbackQuery, Message
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("aiogram is required for Telegram polling") from exc

        dp = Dispatcher()

        @dp.message(CommandStart())
        async def start_handler(message: Message) -> None:
            await self.bot.send_message(message.chat.id, "OpenClaw agent online")


        @dp.callback_query(F.data.startswith("approval:"))
        async def approval_callback(callback: CallbackQuery) -> None:
            _, approval_id, action = callback.data.split(":", 2)
            await self.adapter.on_approval_callback(approval_id, callback.message.chat.id, action)
            await callback.answer("Recorded")

        @dp.message()
        async def message_handler(message: Message) -> None:
            if not message.text:
                return
            thread_id = message.message_thread_id if getattr(message, "is_topic_message", False) else None
            await self.adapter.on_message(message.from_user.id, message.chat.id, message.text, thread_id)

        await dp.start_polling(self.bot)
