from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path

from python_openclaw.channels.telegram_llm_bot import TelegramLLMBotAdapter, TelegramLLMBotRunner
from python_openclaw.channels.telegram_secure_bot import TelegramSecureBotAdapter, TelegramSecureBotRunner
from python_openclaw.cli.onboard import run_onboard
from python_openclaw.gateway.approvals import ApprovalManager
from python_openclaw.gateway.core import GatewayCore
from python_openclaw.gateway.ipc_server import IPCClient
from python_openclaw.gateway.policy import GatewayPolicy
from python_openclaw.gateway.secrets.store import SecretStore
from python_openclaw.gateway.sessions import IdentityManager
from python_openclaw.gateway.secure_web import SecureWebConfig, SecureWebRequester
from python_openclaw.gateway.transcript import TranscriptStore
from python_openclaw.security.gate import ApprovalGate
from python_openclaw.security.permissions import PermissionEnforcer, PermissionStore
from python_openclaw.worker.worker_main import Worker


@dataclass
class OpenClawRuntime:
    llm_runner: TelegramLLMBotRunner
    secure_runner: TelegramSecureBotRunner


async def run_openclaw(base_dir: Path | None = None) -> None:
    runtime = build_runtime(base_dir)
    await asyncio.gather(runtime.llm_runner.run_polling(), runtime.secure_runner.run_polling())


def build_runtime(base_dir: Path | None = None) -> OpenClawRuntime:
    base = base_dir or Path.cwd()
    cfg_path = base / "openclaw.json"
    if not cfg_path.exists():
        run_onboard(base)

    config = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}

    secrets = SecretStore(base / "secrets.enc")
    permission_store = PermissionStore(base / "permissions.db")
    approval_gate = ApprovalGate(permission_store)
    identities = IdentityManager()

    operator_ids = set(config.get("operators", []))
    user_ids = set(config.get("llm_users", []))
    for uid in operator_ids:
        identities.allow_operator(int(uid))
    for uid in user_ids:
        identities.allow_llm_user(int(uid))

    policy = GatewayPolicy(allowed_hosts=set(config.get("allowed_hosts", [])))
    secure_web = SecureWebRequester(
        policy,
        secrets,
        SecureWebConfig(
            header_allowlist={"accept", "content-type", "user-agent"},
            auth_host_permissions={"github": {"api.github.com"}},
        ),
        permission_enforcer=PermissionEnforcer(store=permission_store),
    )

    worker = Worker()
    core = GatewayCore(
        identities=identities,
        transcripts=TranscriptStore(base / "transcripts"),
        ipc_client=IPCClient(worker),
        secure_web=secure_web,
        approvals=ApprovalManager(),
        approval_gate=approval_gate,
    )

    llm_adapter = TelegramLLMBotAdapter(gateway=core, identities=identities, bot_client=_NoopBotClient())
    secure_adapter = TelegramSecureBotAdapter(
        identities=identities,
        approvals=core.approvals,
        secrets=secrets,
        bot_client=_NoopBotClient(),
        approval_gate=approval_gate,
    )

    llm_token = os.getenv("OPENCLAW_AGENT_BOT_TOKEN", "")
    secure_token = os.getenv("OPENCLAW_GATE_BOT_TOKEN", "")
    if not llm_token or not secure_token:
        raise RuntimeError("OPENCLAW_AGENT_BOT_TOKEN and OPENCLAW_GATE_BOT_TOKEN are required")

    return OpenClawRuntime(
        llm_runner=TelegramLLMBotRunner(llm_adapter, llm_token),
        secure_runner=TelegramSecureBotRunner(secure_adapter, secure_token),
    )


class _NoopBotClient:
    async def send_message(self, *_args, **_kwargs):
        return None

    async def send_message_stream(self, *_args, **_kwargs):
        return None

    async def send_photo(self, *_args, **_kwargs):
        return None

    async def send_document(self, *_args, **_kwargs):
        return None

    async def send_approval(self, *_args, **_kwargs):
        return None
