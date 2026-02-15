from __future__ import annotations

from dataclasses import dataclass, field

from python_openclaw.gateway.approvals import ApprovalManager
from python_openclaw.gateway.secrets.store import SecretStore
from python_openclaw.gateway.sessions import IdentityManager


@dataclass
class TelegramSecureBotAdapter:
    identities: IdentityManager
    approvals: ApprovalManager
    secrets: SecretStore
    bot_client: object
    pending_setsecret: dict[int, str] = field(default_factory=dict)

    async def on_message(self, user_id: int, chat_id: int, text: str) -> None:
        if not self.identities.is_operator_allowed(user_id):
            await self.bot_client.send_message(chat_id, "Access denied")
            return

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

    async def send_approval_request(self, chat_id: int, approval_request) -> None:
        p = approval_request.payload
        await self.bot_client.send_approval(
            chat_id,
            approval_request.approval_id,
            {
                "principal": approval_request.principal_id,
                "method": p.get("method"),
                "host": p.get("host"),
                "path": p.get("path"),
                "auth_handle": p.get("auth_handle"),
            },
        )

    async def on_approval_callback(self, approval_id: str, approved: bool, chat_id: int) -> None:
        token = self.approvals.decide(approval_id, approved)
        if approved:
            await self.bot_client.send_message(chat_id, f"Approved {approval_id}. token={token}")
        else:
            await self.bot_client.send_message(chat_id, f"Denied {approval_id}")
