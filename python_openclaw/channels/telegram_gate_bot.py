from __future__ import annotations

from dataclasses import dataclass

from python_openclaw.common.models import Principal
from python_openclaw.gateway.core import GatewayCore
from python_openclaw.gateway.sessions import IdentityManager


@dataclass
class TelegramGateBotClient:
    bot: object

    async def send_message(self, chat_id: int, text: str, reply_markup: object | None = None) -> None:
        await self.bot.send_message(chat_id, text, reply_markup=reply_markup)


@dataclass
class TelegramGateBotAdapter:
    gateway: GatewayCore
    identities: IdentityManager
    bot_client: TelegramGateBotClient

    async def send_approval_request(self, approval_id: str, context: dict) -> None:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        session_key = context.get("session_key", "")
        chat_id = int(session_key.split(":")[-1]) if str(session_key).startswith("tg:dm:") else session_key
        text = (
            f"Permission request: {context.get('resource_type')}={context.get('resource_value')}\n"
            f"Principal: {context.get('principal')}"
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
        await self.bot_client.send_message(chat_id, text, reply_markup=kb)

    async def send_secret_request(self, session_key: str, principal_id: str, handle: str) -> None:
        chat_id = int(session_key.split(":")[-1]) if str(session_key).startswith("tg:dm:") else session_key
        await self.bot_client.send_message(
            chat_id,
            f"Secret required for principal {principal_id}: `{handle}`. Reply with the secret value in your next message.",
        )

    async def send_gate_message(self, session_key: str, text: str) -> None:
        chat_id = int(session_key.split(":")[-1]) if str(session_key).startswith("tg:dm:") else session_key
        await self.bot_client.send_message(chat_id, text)

    async def on_message(self, user_id: int, chat_id: int, text: str) -> None:
        principal = self.identities.principal_for("telegram_gate", str(user_id))
        if principal is None:
            await self.bot_client.send_message(chat_id, "Secure gate identity not bound")
            return

        pending = self.gateway.pending_secret_handle_for(principal.principal_id)
        if pending:
            stored = await self.gateway.handle_secret_reply(principal, text)
            if stored:
                await self.bot_client.send_message(chat_id, f"Stored secret '{stored}'.")
                return

        command, _, arg = text.partition(" ")
        if command == "/unlock":
            self.gateway.secure_web.secrets.unlock(arg.strip())
            await self.bot_client.send_message(chat_id, "Secret store unlocked")
            return
        if command == "/bind":
            target = arg.strip() or principal.principal_id
            self.identities.bind_gate_channel(target, f"tg:dm:{chat_id}")
            await self.bot_client.send_message(chat_id, f"Bound secure gate for {target}")
            return
        if command == "/allow":
            try:
                uid = int(arg.strip())
            except ValueError:
                await self.bot_client.send_message(chat_id, "Usage: /allow <telegram_user_id>")
                return
            self.identities.allow_llm_user(uid)
            await self.bot_client.send_message(chat_id, f"Allowed LLM user {uid}")
            return

        await self.bot_client.send_message(chat_id, "Secure gate online")

    async def on_approval_callback(self, approval_id: str, chat_id: int, action: str | None = None) -> None:
        if not action:
            await self.bot_client.send_message(chat_id, "Missing action")
            return
        prompt = self.gateway.approval_gate.apply_callback(approval_id, action)
        if not prompt:
            await self.bot_client.send_message(chat_id, "Approval request not found")
            return
        await self.bot_client.send_message(chat_id, f"Recorded {action} for {prompt.resource_type}:{prompt.resource_value}")


class TelegramGateBotRunner:
    def __init__(self, adapter: TelegramGateBotAdapter, bot: object):
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
            await self.bot.send_message(message.chat.id, "OpenClaw secure gate online")

        @dp.callback_query(F.data.startswith("approval:"))
        async def approval_callback(callback: CallbackQuery) -> None:
            _, approval_id, action = callback.data.split(":", 2)
            await self.adapter.on_approval_callback(approval_id, callback.message.chat.id, action)
            await callback.answer("Recorded")

        @dp.message()
        async def message_handler(message: Message) -> None:
            if not message.text:
                return
            await self.adapter.on_message(message.from_user.id, message.chat.id, message.text)

        await dp.start_polling(self.bot)
