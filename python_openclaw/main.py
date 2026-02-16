from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from python_openclaw.channels.telegram_llm_bot import TelegramLLMBotAdapter, TelegramLLMBotClient, TelegramLLMBotRunner
from python_openclaw.channels.telegram_gate_bot import TelegramGateBotAdapter, TelegramGateBotClient, TelegramGateBotRunner
from python_openclaw.cli.onboard import run_onboard
from python_openclaw.common.models import Binding, Principal
from python_openclaw.gateway.core import GatewayCore
from python_openclaw.gateway.credentials import CredentialStore
from python_openclaw.gateway.identity_store import IdentityStore
from python_openclaw.gateway.ipc_server import IPCClient
from python_openclaw.gateway.master_password import verify_password
from python_openclaw.gateway.policy import GatewayPolicy
from python_openclaw.gateway.secrets.store import SecretStore
from python_openclaw.gateway.services import RequestService, ToolsService
from python_openclaw.gateway.sessions import IdentityManager
from python_openclaw.gateway.secure_web import SecureWebConfig, SecureWebRequester
from python_openclaw.gateway.transcript import TranscriptStore
from python_openclaw.gateway.unlock_server import UnlockCoordinator, UnlockDependencies, run_unlock_server
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
    credentials: CredentialStore
    identity_store: IdentityStore
    secrets: SecretStore


def _load_config(base_dir: Path) -> dict:
    cfg_path = base_dir / "openclaw.json"
    if not cfg_path.exists():
        run_onboard(base_dir)
    return json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}


def _build_context(base: Path) -> RuntimeContext:
    config = _load_config(base)
    mode = config.get("storage_mode", "plaintext")

    secrets = SecretStore(base / "secrets.enc")
    credentials = CredentialStore(base / "credentials.json", base / "credentials.enc", mode=mode)
    identity_store = IdentityStore(base / "identity.json", base / "identity.enc", mode="encrypted" if mode == "encrypted" else "plaintext")

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

    if identity_store.is_encrypted_mode() and identity_store.unlocked:
        identities.load_from_dict(identity_store.load())
    elif (not identity_store.is_encrypted_mode()) and identity_store.path_plain.exists():
        identities.load_from_dict(identity_store.load())

    permission_store = PermissionStore(base / "permissions.db")
    approval_gate = ApprovalGate(permission_store)

    secure_web = SecureWebRequester(
        GatewayPolicy(allowed_hosts=set(config.get("allowed_hosts", []))),
        secrets,
        SecureWebConfig(
            header_allowlist={"accept", "content-type", "user-agent"},
            secret_header_allowlist={"authorization", "x-api-key"},
            secret_handle_allowed_hosts={handle: set(hosts) for handle, hosts in config.get("secret_handle_allowed_hosts", {"github": ["api.github.com"]}).items()},
        ),
        permission_enforcer=PermissionEnforcer(store=permission_store),
    )

    def _is_locked() -> bool:
        if mode != "encrypted":
            return False
        return not (secrets.unlocked and credentials.unlocked and identity_store.unlocked)

    def _persist_identity(state: dict) -> None:
        if identity_store.is_encrypted_mode():
            return
        identity_store.persist_unlocked(state, master_password="")

    core = GatewayCore(
        identities=identities,
        transcripts=TranscriptStore(base / "transcripts"),
        ipc_client=IPCClient(),
        secure_web=secure_web,
        approval_gate=approval_gate,
        tools=ToolsService(permission_store, secrets),
        requests=RequestService(permission_store, secrets),
        locked_predicate=_is_locked,
        identity_persist_callback=_persist_identity,
    )
    return RuntimeContext(config=config, core=core, identities=identities, credentials=credentials, identity_store=identity_store, secrets=secrets)


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
    agent_token, gate_token = ctx.credentials.get_telegram_tokens()
    llm_bot = _build_bot(agent_token)
    gate_bot = _build_bot(gate_token)

    llm_adapter = TelegramLLMBotAdapter(gateway=ctx.core, identities=ctx.identities, bot_client=TelegramLLMBotClient(llm_bot))
    gate_adapter = TelegramGateBotAdapter(gateway=ctx.core, identities=ctx.identities, bot_client=TelegramGateBotClient(gate_bot))
    ctx.core.set_secure_gate_adapter(gate_adapter)

    return OpenClawRuntime(llm_runner=TelegramLLMBotRunner(llm_adapter, llm_bot), gate_runner=TelegramGateBotRunner(gate_adapter, gate_bot))


def build_runtime(base_dir: Path | None = None) -> OpenClawRuntime:
    base = base_dir or Path.cwd()
    ctx = _build_context(base)
    if ctx.config.get("storage_mode", "plaintext") == "encrypted" and not ctx.credentials.unlocked:
        raise RuntimeError("credentials are locked; unlock required")
    return _runtime_from_context(ctx)


def build_agent_runtime(base_dir: Path | None = None) -> TelegramLLMBotRunner:
    runtime = build_runtime(base_dir)
    return runtime.llm_runner


def build_gate_runtime(base_dir: Path | None = None) -> TelegramGateBotRunner:
    runtime = build_runtime(base_dir)
    return runtime.gate_runner


async def run_openclaw(base_dir: Path | None = None) -> None:
    base = base_dir or Path.cwd()
    ctx = _build_context(base)
    mode = ctx.config.get("storage_mode", "plaintext")

    if mode == "encrypted" and not ctx.credentials.unlocked:
        verifier_path = base / "master.json"
        if not verifier_path.exists():
            raise RuntimeError("master verifier missing")
        verifier = json.loads(verifier_path.read_text(encoding="utf-8"))
        unlocked_event = asyncio.Event()

        def _unlock(password: str) -> None:
            if not verify_password(password, verifier):
                raise RuntimeError("wrong password")
            ctx.secrets.unlock(password)
            ctx.credentials.unlock(password)
            ctx.identity_store.unlock(password)
            ctx.identities.load_from_dict(ctx.identity_store.load())
            unlocked_event.set()

        coordinator = UnlockCoordinator(UnlockDependencies(verify_record=verifier, unlock_callback=_unlock))
        stop_event = asyncio.Event()
        server_task = asyncio.create_task(
            run_unlock_server(
                coordinator,
                host=ctx.config.get("unlock_host", "127.0.0.1"),
                port=int(ctx.config.get("unlock_port", 8443)),
                cert_path=base / "unlock-cert.pem",
                key_path=base / "unlock-key.pem",
                stop_event=stop_event,
            )
        )
        print(f"Open https://{ctx.config.get('unlock_host', '127.0.0.1')}:{int(ctx.config.get('unlock_port', 8443))} to unlock")
        await unlocked_event.wait()
        stop_event.set()
        await server_task

    runtime = _runtime_from_context(ctx)
    await asyncio.gather(runtime.llm_runner.run_polling(), runtime.gate_runner.run_polling())
