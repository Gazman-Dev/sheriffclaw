from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path

from python_openclaw.channels.telegram_llm_bot import TelegramLLMBotAdapter, TelegramLLMBotClient, TelegramLLMBotRunner
from python_openclaw.channels.telegram_gate_bot import TelegramGateBotAdapter, TelegramGateBotClient, TelegramGateBotRunner
from python_openclaw.common.models import Binding, Principal
from python_openclaw.cli.onboard import run_onboard
from python_openclaw.gateway.core import GatewayCore
from python_openclaw.gateway.ipc_server import IPCClient
from python_openclaw.gateway.policy import GatewayPolicy
from python_openclaw.gateway.secrets.store import SecretStore
from python_openclaw.gateway.services import RequestService, ToolsService
from python_openclaw.gateway.sessions import IdentityManager
from python_openclaw.gateway.secure_web import SecureWebConfig, SecureWebRequester
from python_openclaw.gateway.transcript import TranscriptStore
from python_openclaw.security.gate import ApprovalGate
from python_openclaw.security.permissions import PermissionEnforcer, PermissionStore
from python_openclaw.worker.worker_main import Worker


@dataclass
class OpenClawRuntime:
    llm_runner: TelegramLLMBotRunner
    gate_runner: TelegramGateBotRunner


def _load_config(base_dir: Path) -> dict:
    cfg_path = base_dir / "openclaw.json"
    if not cfg_path.exists():
        run_onboard(base_dir)
    return json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}


def _build_core(base: Path) -> tuple[GatewayCore, IdentityManager]:
    config = _load_config(base)
    secrets = SecretStore(base / "secrets.enc", passphrase=os.getenv("OPENCLAW_SECRETS_PASSPHRASE"))
    permission_store = PermissionStore(base / "permissions.db")
    approval_gate = ApprovalGate(permission_store)
    identities = IdentityManager()

    llm_users = set(config.get("users", config.get("llm_users", [])))
    gate_users = set(config.get("gate_users", []))

    for uid in llm_users:
        principal_id = f"tg:{int(uid)}"
        identities.add_principal(Principal(principal_id=principal_id, role="user"))
        identities.bind(Binding(channel="telegram", external_id=str(int(uid)), principal_id=principal_id))
        identities.allow_llm_user(int(uid))

    for uid in gate_users:
        principal_id = f"tg:{int(uid)}"
        if principal_id not in identities.principals:
            identities.add_principal(Principal(principal_id=principal_id, role="user"))
        identities.bind(Binding(channel="telegram_gate", external_id=str(int(uid)), principal_id=principal_id))
        identities.bind_gate_channel(principal_id, f"tg:dm:{int(uid)}")

    secure_web = SecureWebRequester(
        GatewayPolicy(allowed_hosts=set(config.get("allowed_hosts", []))),
        secrets,
        SecureWebConfig(
            header_allowlist={"accept", "content-type", "user-agent"},
            secret_header_allowlist={"authorization", "x-api-key"},
            secret_handle_allowed_hosts={
                handle: set(hosts) for handle, hosts in config.get("secret_handle_allowed_hosts", {"github": ["api.github.com"]}).items()
            },
        ),
        permission_enforcer=PermissionEnforcer(store=permission_store),
    )

    core = GatewayCore(
        identities=identities,
        transcripts=TranscriptStore(base / "transcripts"),
        ipc_client=IPCClient(Worker()),
        secure_web=secure_web,
        approval_gate=approval_gate,
        tools=ToolsService(permission_store, secrets),
        requests=RequestService(permission_store, secrets),
    )
    return core, identities


def _build_bot(token_env_name: str):
    token = os.getenv(token_env_name, "")
    if not token:
        raise RuntimeError(f"{token_env_name} is required")

    try:
        from aiogram import Bot
        from aiogram.enums import ParseMode
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("aiogram is required for Telegram polling") from exc

    return Bot(token, parse_mode=ParseMode.HTML)


def build_runtime(base_dir: Path | None = None) -> OpenClawRuntime:
    base = base_dir or Path.cwd()
    core, identities = _build_core(base)

    llm_bot = _build_bot("OPENCLAW_AGENT_TOKEN")
    gate_bot = _build_bot("OPENCLAW_GATE_TOKEN")

    llm_adapter = TelegramLLMBotAdapter(gateway=core, identities=identities, bot_client=TelegramLLMBotClient(llm_bot))
    gate_adapter = TelegramGateBotAdapter(gateway=core, identities=identities, bot_client=TelegramGateBotClient(gate_bot))
    core.set_secure_gate_adapter(gate_adapter)

    return OpenClawRuntime(
        llm_runner=TelegramLLMBotRunner(llm_adapter, llm_bot),
        gate_runner=TelegramGateBotRunner(gate_adapter, gate_bot),
    )


def build_agent_runtime(base_dir: Path | None = None) -> TelegramLLMBotRunner:
    base = base_dir or Path.cwd()
    core, identities = _build_core(base)
    llm_bot = _build_bot("OPENCLAW_AGENT_TOKEN")
    llm_adapter = TelegramLLMBotAdapter(gateway=core, identities=identities, bot_client=TelegramLLMBotClient(llm_bot))
    return TelegramLLMBotRunner(llm_adapter, llm_bot)


def build_gate_runtime(base_dir: Path | None = None) -> TelegramGateBotRunner:
    base = base_dir or Path.cwd()
    core, identities = _build_core(base)
    gate_bot = _build_bot("OPENCLAW_GATE_TOKEN")
    gate_adapter = TelegramGateBotAdapter(gateway=core, identities=identities, bot_client=TelegramGateBotClient(gate_bot))
    core.set_secure_gate_adapter(gate_adapter)
    return TelegramGateBotRunner(gate_adapter, gate_bot)


async def run_openclaw(base_dir: Path | None = None) -> None:
    runtime = build_runtime(base_dir)
    await asyncio.gather(runtime.llm_runner.run_polling(), runtime.gate_runner.run_polling())
