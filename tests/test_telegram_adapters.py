from pathlib import Path

import asyncio

from python_openclaw.channels.telegram_llm_bot import TelegramLLMBotAdapter
from python_openclaw.channels.telegram_secure_bot import TelegramSecureBotAdapter
from python_openclaw.common.models import Binding, Principal
from python_openclaw.gateway.sessions import IdentityManager
from python_openclaw.gateway.secrets.store import SecretStore
from python_openclaw.security.gate import ApprovalGate
from python_openclaw.security.permissions import PermissionDeniedException, PermissionStore


class FakeBotClient:
    def __init__(self):
        self.messages = []
        self.approvals = []

    async def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))

    async def send_message_stream(self, session_key, text):
        self.messages.append((session_key, text))

    async def send_approval(self, chat_id, approval_id, summary):
        self.approvals.append((chat_id, approval_id, summary))

    async def send_photo(self, session_key, payload):
        self.messages.append((session_key, payload))

    async def send_document(self, session_key, payload):
        self.messages.append((session_key, payload))


class FakeGateway:
    def __init__(self):
        self.calls = []

    async def handle_user_message(self, **kwargs):
        self.calls.append(kwargs)


def test_llm_allowlist_enforced():
    identities = IdentityManager()
    identities.add_principal(Principal("u1", "user"))
    identities.bind(Binding("telegram", "100", "u1"))
    bot = FakeBotClient()
    gateway = FakeGateway()
    adapter = TelegramLLMBotAdapter(gateway=gateway, identities=identities, bot_client=bot)

    asyncio.run(adapter.on_message(100, 1000, "hello"))
    assert bot.messages[-1] == (1000, "Access denied")

    identities.allow_llm_user(100)
    asyncio.run(adapter.on_message(100, 1000, "hello"))
    assert len(gateway.calls) == 1


def test_secure_bot_commands_and_approval_format(tmp_path: Path):
    identities = IdentityManager()
    identities.allow_operator(42)
    bot = FakeBotClient()
    secrets = SecretStore(tmp_path / "secrets.enc")
    approval_gate = ApprovalGate(PermissionStore(tmp_path / "permissions.db"))
    adapter = TelegramSecureBotAdapter(identities=identities, secrets=secrets, bot_client=bot, approval_gate=approval_gate)

    asyncio.run(adapter.on_message(42, 10, "/unlock pw"))
    asyncio.run(adapter.on_message(42, 10, "/setsecret github"))
    asyncio.run(adapter.on_message(42, 10, "Bearer abc"))
    asyncio.run(adapter.on_message(42, 10, "/allow 100"))

    assert any("Secret github stored." in text for _, text in bot.messages)

    prompt = approval_gate.request(PermissionDeniedException("u1", "domain", "api.github.com"))
    asyncio.run(adapter.on_approval_callback(prompt.approval_id, 10, user_id=42, action="always_allow"))
    decision = approval_gate.store.get_decision("u1", "domain", "api.github.com")
    assert decision and decision.decision == "ALLOW"

