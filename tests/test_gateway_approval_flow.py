import asyncio

import pytest

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
from python_openclaw.security.permissions import PermissionDeniedException, PermissionEnforcer, PermissionStore


class FakeSecureGateAdapter:
    def __init__(self):
        self.approvals = []
        self.messages = []

    async def send_approval_request(self, approval_id: str, context: dict) -> None:
        self.approvals.append((approval_id, context))

    async def send_secret_request(self, session_key: str, principal_id: str, handle: str) -> None:
        self.messages.append((session_key, principal_id, handle))

    async def send_gate_message(self, session_key: str, text: str) -> None:
        self.messages.append((session_key, text))


@pytest.fixture
def core(tmp_path, monkeypatch):
    import socket
    import urllib.request

    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [(None, None, None, None, ("93.184.216.34", 0))])

    class Resp:
        headers = {}

        def read(self):
            return b"ok"

        def getcode(self):
            return 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    class Opener:
        def open(self, req, timeout=0):
            return Resp()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())

    identities = IdentityManager()
    identities.bind_gate_channel("u1", "tg:dm:1")
    permission_store = PermissionStore(tmp_path / "permissions.db")
    secure_store = SecretStore(tmp_path / "secrets.enc")
    secure_store.unlock("pw")
    secure_store.set_secret("github", "tok")
    secure_web = SecureWebRequester(
        GatewayPolicy({"api.github.com"}),
        secure_store,
        SecureWebConfig(
            header_allowlist={"accept"},
            secret_header_allowlist={"authorization", "x-api-key"},
            secret_handle_allowed_hosts={"github": {"api.github.com"}},
        ),
        permission_enforcer=PermissionEnforcer(store=permission_store),
    )
    gateway = GatewayCore(
        identities=identities,
        transcripts=TranscriptStore(tmp_path / "t"),
        ipc_client=IPCClient(),
        secure_web=secure_web,
        approval_gate=ApprovalGate(permission_store),
        tools=ToolsService(permission_store, secure_store),
        requests=RequestService(permission_store, secure_store),
    )
    gateway.set_secure_gate_adapter(FakeSecureGateAdapter())
    return gateway


def test_secret_web_request_creates_gate_approval(core: GatewayCore):
    principal = Principal("u1", "user")
    payload = {
        "tool_name": "secure.web.request",
        "payload": {
            "method": "GET",
            "host": "api.github.com",
            "path": "/user",
            "secret_headers": {"Authorization": "github"},
        },
    }
    result = core._handle_tool_call(principal, payload)
    assert result["status"] == "approval_requested"
    assert core.secure_gate_adapter.approvals


def test_disclosure_flow_requires_one_time_approval_and_sends_to_gate(core: GatewayCore):
    principal = Principal("u1", "user")
    store = core.approval_gate.store
    store.set_decision("u1", "tool", "python3", "ALLOW")

    tool_result = core._handle_tool_call(principal, {"tool_name": "tools.exec", "payload": {"argv": ["python3", "-c", "print(42)"], "taint": True}})
    run_id = tool_result["run_id"]

    disclose = core._handle_tool_call(
        principal,
        {"tool_name": "secure.disclose_output", "payload": {"run_id": run_id, "target": "secure_channel"}},
    )
    approval_id = disclose["approval_id"]

    core.approval_gate.apply_callback(approval_id, "approve_this_request")
    asyncio.run(asyncio.sleep(0))

    assert any("Disclosed output" in msg[1] for msg in core.secure_gate_adapter.messages)


def test_allow_once_removed_and_always_allow_persists(core: GatewayCore):
    prompt = core.approval_gate.request(PermissionDeniedException("u1", "domain", "api.github.com"))
    core.approval_gate.apply_callback(prompt.approval_id, "allow_once")
    assert core.approval_gate.store.get_decision("u1", "domain", "api.github.com") is None

    prompt2 = core.approval_gate.request(PermissionDeniedException("u1", "domain", "api.github.com"))
    core.approval_gate.apply_callback(prompt2.approval_id, "always_allow")
    decision = core.approval_gate.store.get_decision("u1", "domain", "api.github.com")
    assert decision and decision.decision == "ALLOW"
