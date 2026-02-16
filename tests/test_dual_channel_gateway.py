from pathlib import Path

import asyncio

from python_openclaw.common.models import Principal
from python_openclaw.gateway.core import GatewayCore
from python_openclaw.gateway.ipc_server import IPCClient
from python_openclaw.gateway.policy import GatewayPolicy
from python_openclaw.gateway.secure_web import SecureWebConfig, SecureWebRequester
from python_openclaw.gateway.secrets.store import SecretStore
from python_openclaw.gateway.services import RequestService, ToolsService
from python_openclaw.gateway.sessions import IdentityManager
from python_openclaw.gateway.transcript import TranscriptStore
from python_openclaw.security.gate import ApprovalGate
from python_openclaw.security.permissions import PermissionStore


class FakeAdapter:
    def __init__(self):
        self.events = []

    async def send_stream(self, session_key: str, event: dict):
        self.events.append((session_key, event))

    async def send_approval_request(self, approval_id: str, context: dict):
        self.events.append((context.get("session_key", ""), {"approval_id": approval_id, "context": context}))


class FakeSecureGate:
    def __init__(self):
        self.approvals = []
        self.secret_requests = []

    async def send_approval_request(self, approval_id: str, context: dict) -> None:
        self.approvals.append((approval_id, context))

    async def send_secret_request(self, session_key: str, principal_id: str, handle: str) -> None:
        self.secret_requests.append((session_key, principal_id, handle))

    async def send_gate_message(self, session_key: str, text: str) -> None:
        return None


def _build_core(tmp_path: Path) -> tuple[GatewayCore, SecretStore]:
    permission_store = PermissionStore(tmp_path / "permissions.db")
    secrets = SecretStore(tmp_path / "secrets.enc")
    secrets.unlock("pw")
    core = GatewayCore(
        identities=IdentityManager(),
        transcripts=TranscriptStore(tmp_path / "transcripts"),
        ipc_client=IPCClient(),
        secure_web=SecureWebRequester(GatewayPolicy(set()), secrets, SecureWebConfig(header_allowlist={"accept"})),
        approval_gate=ApprovalGate(permission_store),
        tools=ToolsService(permission_store, secrets),
        requests=RequestService(permission_store, secrets),
    )
    return core, secrets


def test_permission_request_is_routed_to_secure_gate(tmp_path: Path):
    core, _ = _build_core(tmp_path)
    principal = Principal("u1", "user")
    core.identities.bind_gate_channel("u1", "tg:dm:999")
    secure_gate = FakeSecureGate()
    core.set_secure_gate_adapter(secure_gate)

    result = asyncio.run(
        core._handle_tool_call_async(
            principal,
            {
                "tool_name": "request",
                "payload": {"resource_type": "domain", "resource_value": "api.example.com"},
            },
            adapter=FakeAdapter(),
            source_session_key="tg:dm:100",
        )
    )

    assert result["status"] == "approval_requested"
    assert len(secure_gate.approvals) == 1
    _, context = secure_gate.approvals[0]
    assert context["session_key"] == "tg:dm:999"
    assert context["resource_value"] == "api.example.com"


def test_missing_secret_requests_value_over_secure_gate(tmp_path: Path):
    core, secrets = _build_core(tmp_path)
    principal = Principal("u1", "user")
    core.identities.bind_gate_channel("u1", "tg:dm:999")
    secure_gate = FakeSecureGate()
    core.set_secure_gate_adapter(secure_gate)

    result = asyncio.run(
        core._handle_tool_call_async(
            principal,
            {"tool_name": "secure.secret.ensure", "payload": {"handle": "github_token"}},
            adapter=FakeAdapter(),
            source_session_key="tg:dm:100",
        )
    )

    assert result["status"] == "secret_requested"
    assert secure_gate.secret_requests == [("tg:dm:999", "u1", "github_token")]
    assert core.pending_secret_handle_for("u1") == "github_token"

    stored = asyncio.run(core.handle_secret_reply(principal, "Bearer abc"))
    assert stored == "github_token"
    assert secrets.get_secret("github_token") == "Bearer abc"
