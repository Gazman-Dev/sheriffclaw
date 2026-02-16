from pathlib import Path

import pytest

from python_openclaw.common.models import Principal
from python_openclaw.gateway.core import GatewayCore
from python_openclaw.gateway.ipc_server import IPCClient
from python_openclaw.gateway.policy import GatewayPolicy
from python_openclaw.gateway.secure_web import SecureWebConfig, SecureWebRequester
from python_openclaw.gateway.secrets.store import SecretStore
from python_openclaw.gateway.sessions import IdentityManager
from python_openclaw.gateway.transcript import TranscriptStore
from python_openclaw.security.gate import ApprovalGate
from python_openclaw.security.permissions import PermissionStore


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
    permission_store = PermissionStore(tmp_path / "permissions.db")
    secure_store = SecretStore(tmp_path / "secrets.enc")
    secure_store.unlock("pw")
    secure_store.set_secret("github", "Bearer tok")
    secure_web = SecureWebRequester(
        GatewayPolicy({"api.github.com"}),
        secure_store,
        SecureWebConfig(header_allowlist={"accept"}, auth_host_permissions={"github": {"api.github.com"}}),
    )
    return GatewayCore(
        identities=identities,
        transcripts=TranscriptStore(tmp_path / "t"),
        ipc_client=IPCClient(),
        secure_web=secure_web,
        approval_gate=ApprovalGate(permission_store),
    )


def test_permission_denied_without_allow_rule(core: GatewayCore):
    principal = Principal("u1", "user")
    payload = {
        "tool_name": "secure.web.request",
        "payload": {"method": "GET", "host": "api.github.com", "path": "/user", "auth_handle": "github"},
    }
    result = core._handle_tool_call(principal, payload)
    assert result["status"] in {"permission_denied", "error"}


def test_request_tool_creates_gate_approval(core: GatewayCore):
    principal = Principal("u1", "user")
    payload = {
        "tool_name": "request",
        "payload": {"resource_type": "domain", "resource_value": "api.github.com", "method": "GET", "path": "/user"},
        "reason": "Need GitHub profile",
    }
    result = core._handle_tool_call(principal, payload)
    assert result["status"] == "approval_requested"
    assert result["approval_id"] in core.approval_gate.pending
