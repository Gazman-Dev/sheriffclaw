from pathlib import Path

import pytest

from python_openclaw.common.models import Principal
from python_openclaw.gateway.approvals import ApprovalManager
from python_openclaw.gateway.core import GatewayCore
from python_openclaw.gateway.ipc_server import IPCClient
from python_openclaw.gateway.policy import GatewayPolicy
from python_openclaw.gateway.secure_web import SecureWebConfig, SecureWebRequester
from python_openclaw.gateway.secrets.store import SecretStore
from python_openclaw.gateway.sessions import IdentityManager
from python_openclaw.gateway.transcript import TranscriptStore


@pytest.fixture
def core(tmp_path, monkeypatch):
    import socket
    import urllib.request

    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [(None, None, None, None, ("93.184.216.34", 0))])

    class Resp:
        headers = {}
        def read(self): return b"ok"
        def getcode(self): return 200
        def __enter__(self): return self
        def __exit__(self, *_): return False

    class Opener:
        def open(self, req, timeout=0):
            return Resp()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())

    identities = IdentityManager()
    store = SecretStore(tmp_path / "secrets.enc")
    store.unlock("pw")
    store.set_secret("github", "Bearer tok")
    secure_web = SecureWebRequester(
        GatewayPolicy({"api.github.com"}),
        store,
        SecureWebConfig(header_allowlist={"accept"}, auth_host_permissions={"github": {"api.github.com"}}),
    )
    return GatewayCore(identities, TranscriptStore(tmp_path / "t"), IPCClient(), secure_web, ApprovalManager(ttl_seconds=1))


def test_approval_required_and_deny_blocks(core: GatewayCore):
    principal = Principal("u1", "user")
    payload = {
        "tool_name": "secure.web.request",
        "payload": {"method": "GET", "host": "api.github.com", "path": "/user", "auth_handle": "github"},
        "reason": "because",
    }
    result = core._handle_tool_call(principal, payload)
    assert result["status"] == "approval_required"
    aid = result["approval_id"]
    token = core.approvals.decide(aid, False)
    assert token is None
    with pytest.raises(PermissionError):
        core.execute_approved_web_request(principal.principal_id, payload["payload"], "bad-token")


def test_approved_token_executes_once(core: GatewayCore):
    principal = Principal("u1", "user")
    payload = {
        "tool_name": "secure.web.request",
        "payload": {"method": "GET", "host": "api.github.com", "path": "/user", "auth_handle": "github"},
    }
    result = core._handle_tool_call(principal, payload)
    token = core.approvals.decide(result["approval_id"], True)
    response = core.execute_approved_web_request(principal.principal_id, payload["payload"], token)
    assert response["status"] == 200
    with pytest.raises(PermissionError):
        core.execute_approved_web_request(principal.principal_id, payload["payload"], token)
