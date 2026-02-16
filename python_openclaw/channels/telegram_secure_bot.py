from __future__ import annotations

from dataclasses import dataclass, field

from python_openclaw.gateway.secrets.store import SecretStore
from python_openclaw.gateway.sessions import IdentityManager
from python_openclaw.security.gate import ApprovalGate


@dataclass
class TelegramSecureBotClient:
    bot: object

    async def send_message(self, chat_id: int, text: str) -> None:
        await self.bot.send_message(chat_id, text)

    async def send_approval(self, chat_id: int, approval_id: str, summary: dict) -> None:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

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
class TelegramSecureBotAdapter:
    identities: IdentityManager
    secrets: SecretStore
    bot_client: object
    approval_gate: ApprovalGate
    pending_setsecret: dict[int, str] = field(default_factory=dict)

    async def on_message(self, user_id: int, chat_id: int, text: str) -> None:
        if not self.identities.is_operator_allowed(user_id):
            await self.bot_client.send_message(chat_id, "Access denied")
            return

        self.identities.bind_gate_channel(f"telegram:{user_id}", f"tg:dm:{chat_id}")

        if user_id in self.pending_setsecret:
            handle = self.pending_setsecret.pop(user_id)
            self.secrets.set_secret(handle, text)
            await self.bot_client.send_message(chat_id, f"Secret {handle} stored.")
            return

        if text.startswith("/unlock "):
            passphrase = text.split(" ", 1)[1]
            self.secrets.unlock(passphrase)
            await self.bot_client.send_message(chat_id, "Secret store unlocked")
        elif text == "/lock":
            self.secrets.lock()
            await self.bot_client.send_message(chat_id, "Secret store locked")
        elif text.startswith("/setsecret "):
            handle = text.split(" ", 1)[1].strip()
            self.pending_setsecret[user_id] = handle
            await self.bot_client.send_message(chat_id, f"Send value for {handle}")
        elif text.startswith("/allow "):
            allowed = int(text.split(" ", 1)[1])
            self.identities.allow_llm_user(allowed)
            await self.bot_client.send_message(chat_id, f"Allowed {allowed}")
        else:
            await self.bot_client.send_message(chat_id, "Unknown command")

    async def on_approval_callback(self, approval_id: str, chat_id: int, *, user_id: int | None = None, action: str | None = None) -> None:
        if user_id is not None and not self.identities.is_operator_allowed(user_id):
            await self.bot_client.send_message(chat_id, "Unauthorized callback")
            return

        if not action:
            await self.bot_client.send_message(chat_id, "Missing action")
            return

        prompt = self.approval_gate.apply_callback(approval_id, action)
        if not prompt:
            await self.bot_client.send_message(chat_id, "Approval request not found")
            return
        await self.bot_client.send_message(chat_id, f"Recorded {action} for {prompt.resource_type}:{prompt.resource_value}")


class TelegramSecureBotRunner:
    def __init__(self, adapter: TelegramSecureBotAdapter, bot: object):
        self.adapter = adapter
        self.bot = bot

    async def run_polling(self) -> None:
        try:
            from aiogram import Dispatcher, F
            from aiogram.types import CallbackQuery, Message
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("aiogram is required for Telegram polling") from exc

        dp = Dispatcher()

        @dp.message()
        async def secure_message_handler(message: Message) -> None:
            if message.text:
                await self.adapter.on_message(message.from_user.id, message.chat.id, message.text)

        @dp.callback_query(F.data.startswith("approval:"))
        async def approval_callback(callback: CallbackQuery) -> None:
            _, approval_id, action = callback.data.split(":", 2)
            await self.adapter.on_approval_callback(
                approval_id,
                chat_id=callback.message.chat.id,
                user_id=callback.from_user.id,
                action=action,
            )
            await callback.answer("Recorded")

        await dp.start_polling(self.bot)
