from __future__ import annotations

import asyncio
import getpass
import json
from dataclasses import dataclass
from pathlib import Path

from python_openclaw.channels.telegram_gate_bot import TelegramGateBotAdapter, TelegramGateBotClient, TelegramGateBotRunner
from python_openclaw.channels.telegram_llm_bot import TelegramLLMBotAdapter, TelegramLLMBotClient, TelegramLLMBotRunner
from python_openclaw.cli.onboard import run_onboard
from python_openclaw.common.models import Binding, Principal
from python_openclaw.gateway.core import GatewayCore
from python_openclaw.gateway.ipc_server import IPCClient
from python_openclaw.gateway.policy import GatewayPolicy
from python_openclaw.gateway.secrets.service import SecretsService
from python_openclaw.gateway.secrets.store import SecretLockedError, SecretNotFoundError
from python_openclaw.gateway.secure_web import SecureWebConfig, SecureWebRequester
from python_openclaw.gateway.services import RequestService, ToolsService
from python_openclaw.gateway.sessions import IdentityManager
from python_openclaw.gateway.transcript import TranscriptStore
from python_openclaw.security.gate import ApprovalGate
from python_openclaw.security.permissions import PermissionEnforcer, PermissionStore


@dataclass
class OpenClawRuntime:
    llm_runner: TelegramLLMBotRunner
    gate_runner: TelegramGateBotRunner


@dataclass
class RuntimeContext:
    config: dict
    core: GatewayCore
    identities: IdentityManager
    secrets_service: SecretsService


class _SecretFacade:
    def __init__(self, service: SecretsService):
        self.service = service

    @property
    def unlocked(self) -> bool:
        return self.service.unlocked

    def unlock(self, password: str) -> None:
        self.service.unlock(password)

    def set_secret(self, handle: str, value: str) -> None:
        self.service.set_secret(handle, value)

    def get_secret(self, handle: str) -> str:
        if not self.service.unlocked:
            raise SecretLockedError("secret store locked")
        try:
            return self.service.get_secret(handle)
        except KeyError as exc:
            raise SecretNotFoundError(handle) from exc


def _load_config(base_dir: Path) -> dict:
    cfg_path = base_dir / "openclaw.json"
    if not cfg_path.exists():
        run_onboard(base_dir)
    return json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}


def _build_context(base: Path) -> RuntimeContext:
    config = _load_config(base)
    service = SecretsService(
        encrypted_path=base / "secrets_service.enc",
        master_verifier_path=base / "master.json",
        telegram_secrets_path=base / "telegram_secrets_channel.json",
    )
    secrets = _SecretFacade(service)

    identities = IdentityManager()
    if service.unlocked:
        identity_state = service.get_identity_state()
    else:
        identity_state = {"llm_allowed_telegram_user_ids": [], "gate_bindings": {}, "trusted_gate_user_ids": []}
    identities.load_from_dict(identity_state)
    for uid in identity_state.get("llm_allowed_telegram_user_ids", []):
        principal_id = f"tg:{int(uid)}"
        identities.add_principal(Principal(principal_id=principal_id, role="user"))
        identities.bind(Binding(channel="telegram", external_id=str(int(uid)), principal_id=principal_id))
    for uid in identity_state.get("trusted_gate_user_ids", []):
        principal_id = f"tg:{int(uid)}"
        if principal_id not in identities.principals:
            identities.add_principal(Principal(principal_id=principal_id, role="user"))
        identities.bind(Binding(channel="telegram_gate", external_id=str(int(uid)), principal_id=principal_id))

    permission_store = PermissionStore(base / "permissions.db")
    approval_gate = ApprovalGate(permission_store)

    secure_web = SecureWebRequester(
        GatewayPolicy(allowed_hosts=set(config.get("allowed_hosts", []))),
        secrets,
        SecureWebConfig(
            header_allowlist={"accept", "content-type", "user-agent"},
            secret_header_allowlist={"authorization", "x-api-key"},
            secret_handle_allowed_hosts={
                handle: set(hosts)
                for handle, hosts in config.get("secret_handle_allowed_hosts", {"github": ["api.github.com"]}).items()
            },
        ),
        permission_enforcer=PermissionEnforcer(store=permission_store),
    )

    core = GatewayCore(
        identities=identities,
        transcripts=TranscriptStore(base / "transcripts"),
        ipc_client=IPCClient(),
        secure_web=secure_web,
        approval_gate=approval_gate,
        tools=ToolsService(permission_store, secrets),
        requests=RequestService(permission_store, secrets),
        locked_predicate=lambda: not service.unlocked,
        identity_persist_callback=lambda state: service.save_identity_state(state) if service.unlocked else None,
    )
    return RuntimeContext(config=config, core=core, identities=identities, secrets_service=service)


def _build_bot(token: str):
    if not token:
        raise RuntimeError("bot token is required")
    try:
        from aiogram import Bot
        from aiogram.enums import ParseMode
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("aiogram is required for Telegram polling") from exc
    return Bot(token, parse_mode=ParseMode.HTML)


def _runtime_from_context(ctx: RuntimeContext) -> OpenClawRuntime:
    llm_bot = _build_bot(ctx.secrets_service.get_llm_bot_token())
    gate_bot = _build_bot(ctx.secrets_service.get_gate_bot_token())

    llm_adapter = TelegramLLMBotAdapter(gateway=ctx.core, identities=ctx.identities, bot_client=TelegramLLMBotClient(llm_bot))
    gate_adapter = TelegramGateBotAdapter(
        gateway=ctx.core,
        identities=ctx.identities,
        bot_client=TelegramGateBotClient(gate_bot),
        secrets_service=ctx.secrets_service,
    )
    ctx.core.set_secure_gate_adapter(gate_adapter)
    return OpenClawRuntime(llm_runner=TelegramLLMBotRunner(llm_adapter, llm_bot), gate_runner=TelegramGateBotRunner(gate_adapter, gate_bot))


def build_runtime(base_dir: Path | None = None) -> OpenClawRuntime:
    base = base_dir or Path.cwd()
    ctx = _build_context(base)
    if not ctx.secrets_service.unlocked:
        raise RuntimeError("runtime is locked; unlock required")
    return _runtime_from_context(ctx)


def build_agent_runtime(base_dir: Path | None = None) -> TelegramLLMBotRunner:
    runtime = build_runtime(base_dir)
    return runtime.llm_runner


def build_gate_runtime(base_dir: Path | None = None) -> TelegramGateBotRunner:
    base = base_dir or Path.cwd()
    ctx = _build_context(base)
    if ctx.secrets_service.unlocked:
        return _runtime_from_context(ctx).gate_runner
    if not ctx.secrets_service.gate_channel_uses_plaintext_config():
        raise RuntimeError("gate runtime is locked; unlock required")
    gate_bot = _build_bot(ctx.secrets_service.get_gate_bot_token())
    gate_adapter = TelegramGateBotAdapter(
        gateway=ctx.core,
        identities=ctx.identities,
        bot_client=TelegramGateBotClient(gate_bot),
        secrets_service=ctx.secrets_service,
    )
    ctx.core.set_secure_gate_adapter(gate_adapter)
    return TelegramGateBotRunner(gate_adapter, gate_bot)


async def run_openclaw(base_dir: Path | None = None) -> None:
    base = base_dir or Path.cwd()
    ctx = _build_context(base)

    if not ctx.secrets_service.unlocked and not ctx.secrets_service.gate_channel_uses_plaintext_config():
        password = getpass.getpass("Master password: ")
        ctx.secrets_service.unlock(password)

    if ctx.secrets_service.unlocked:
        runtime = _runtime_from_context(ctx)
        await asyncio.gather(runtime.llm_runner.run_polling(), runtime.gate_runner.run_polling())
        return

    # Telegram-based unlock mode: boot secure gate first, then start LLM channel after /unlock.
    gate_bot = _build_bot(ctx.secrets_service.get_gate_bot_token())
    unlocked_event = asyncio.Event()
    gate_adapter = TelegramGateBotAdapter(
        gateway=ctx.core,
        identities=ctx.identities,
        bot_client=TelegramGateBotClient(gate_bot),
        secrets_service=ctx.secrets_service,
        on_unlock=lambda: unlocked_event.set(),
    )
    ctx.core.set_secure_gate_adapter(gate_adapter)
    gate_runner = TelegramGateBotRunner(gate_adapter, gate_bot)
    gate_task = asyncio.create_task(gate_runner.run_polling())
    await unlocked_event.wait()

    identity_state = ctx.secrets_service.get_identity_state()
    for uid in identity_state.get("llm_allowed_telegram_user_ids", []):
        principal_id = f"tg:{int(uid)}"
        if principal_id not in ctx.identities.principals:
            ctx.identities.add_principal(Principal(principal_id=principal_id, role="user"))
            ctx.identities.bind(Binding(channel="telegram", external_id=str(int(uid)), principal_id=principal_id))

    llm_bot = _build_bot(ctx.secrets_service.get_llm_bot_token())
    llm_adapter = TelegramLLMBotAdapter(gateway=ctx.core, identities=ctx.identities, bot_client=TelegramLLMBotClient(llm_bot))
    llm_runner = TelegramLLMBotRunner(llm_adapter, llm_bot)
    await asyncio.gather(gate_task, llm_runner.run_polling())
