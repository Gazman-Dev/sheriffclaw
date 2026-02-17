import asyncio

from python_openclaw.channels.telegram_gate_bot import TelegramGateBotAdapter
from python_openclaw.gateway.core import GatewayCore
from python_openclaw.gateway.ipc_server import IPCClient
from python_openclaw.gateway.policy import GatewayPolicy
from python_openclaw.gateway.secrets.service import SecretsService
from python_openclaw.gateway.secure_web import SecureWebConfig, SecureWebRequester
from python_openclaw.gateway.services import RequestService, ToolsService
from python_openclaw.gateway.sessions import IdentityManager
from python_openclaw.gateway.transcript import TranscriptStore
from python_openclaw.security.gate import ApprovalGate
from python_openclaw.security.permissions import PermissionEnforcer, PermissionStore


class Bot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.messages.append((chat_id, text))


def _make_gateway(tmp_path, service):
    identities = IdentityManager()
    permission_store = PermissionStore(tmp_path / "permissions.db")
    secrets = type("S", (), {"set_secret": service.set_secret, "get_secret": service.get_secret, "unlocked": service.unlocked})()
    secure_web = SecureWebRequester(
        GatewayPolicy(allowed_hosts={"api.github.com"}),
        secrets,
        SecureWebConfig(
            header_allowlist={"accept", "content-type"},
            secret_header_allowlist={"authorization"},
            secret_handle_allowed_hosts={"github": {"api.github.com"}},
        ),
        permission_enforcer=PermissionEnforcer(store=permission_store),
    )
    gateway = GatewayCore(
        identities=identities,
        transcripts=TranscriptStore(tmp_path / "transcripts"),
        ipc_client=IPCClient(),
        secure_web=secure_web,
        approval_gate=ApprovalGate(permission_store),
        tools=ToolsService(permission_store, secrets),
        requests=RequestService(permission_store, secrets),
    )
    return gateway, identities


def test_gate_rejects_untrusted_user(tmp_path):
    service = SecretsService(
        encrypted_path=tmp_path / "secrets_service.enc",
        master_verifier_path=tmp_path / "master.json",
        telegram_secrets_path=tmp_path / "telegram_secrets_channel.json",
    )
    service.initialize(
        master_password="pw",
        provider="openai",
        llm_api_key="sk",
        llm_bot_token="llm",
        gate_bot_token="gate",
        allow_telegram_master_password=True,
    )
    service.lock()
    gateway, identities = _make_gateway(tmp_path, service)
    bot = Bot()
    adapter = TelegramGateBotAdapter(gateway=gateway, identities=identities, bot_client=bot, secrets_service=service)

    asyncio.run(adapter.on_message(123, 123, "/unlock pw"))
    assert bot.messages[-1] == (123, "Secure gate user is not trusted")


def test_gate_unlocks_for_trusted_user(tmp_path):
    service = SecretsService(
        encrypted_path=tmp_path / "secrets_service.enc",
        master_verifier_path=tmp_path / "master.json",
        telegram_secrets_path=tmp_path / "telegram_secrets_channel.json",
    )
    service.initialize(
        master_password="pw",
        provider="openai",
        llm_api_key="sk",
        llm_bot_token="llm",
        gate_bot_token="gate",
        allow_telegram_master_password=True,
    )
    service.add_trusted_gate_user(123)
    service.lock()
    gateway, identities = _make_gateway(tmp_path, service)
    bot = Bot()
    unlocked = {"value": False}
    adapter = TelegramGateBotAdapter(
        gateway=gateway,
        identities=identities,
        bot_client=bot,
        secrets_service=service,
        on_unlock=lambda: unlocked.__setitem__("value", True),
    )

    asyncio.run(adapter.on_message(123, 123, "/unlock pw"))
    assert bot.messages[-1] == (123, "Unlocked")
    assert unlocked["value"]
