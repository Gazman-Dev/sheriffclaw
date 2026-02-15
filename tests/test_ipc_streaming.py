from pathlib import Path

import asyncio

from python_openclaw.common.models import Binding, Principal
from python_openclaw.gateway.approvals import ApprovalManager
from python_openclaw.gateway.core import GatewayCore
from python_openclaw.gateway.ipc_server import IPCClient
from python_openclaw.gateway.policy import GatewayPolicy
from python_openclaw.gateway.secure_web import SecureWebConfig, SecureWebRequester
from python_openclaw.gateway.secrets.store import SecretStore
from python_openclaw.gateway.sessions import IdentityManager
from python_openclaw.gateway.transcript import TranscriptStore


class MockChannel:
    def __init__(self):
        self.events = []

    async def send_stream(self, session_key: str, event: dict):
        self.events.append((session_key, event))


def test_gateway_forwards_worker_stream(tmp_path: Path, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [(None, None, None, None, ("93.184.216.34", 0))])

    identities = IdentityManager()
    identities.add_principal(Principal("u1", "user"))
    identities.bind(Binding("telegram", "123", "u1"))

    store = SecretStore(tmp_path / "secrets.enc")
    store.unlock("pw")
    store.set_secret("github", "Bearer tok")
    secure_web = SecureWebRequester(
        GatewayPolicy({"api.github.com"}),
        store,
        SecureWebConfig(header_allowlist={"accept"}, auth_host_permissions={"github": {"api.github.com"}}),
    )

    core = GatewayCore(
        identities=identities,
        transcripts=TranscriptStore(tmp_path / "transcripts"),
        ipc_client=IPCClient(),
        secure_web=secure_web,
        approvals=ApprovalManager(),
    )

    channel = MockChannel()
    asyncio.run(core.handle_user_message(
        channel="telegram_dm",
        context={"user_id": 123},
        principal=Principal("u1", "user"),
        text="hello world",
        adapter=channel,
    ))

    streams = [e[1]["stream"] for e in channel.events]
    assert "assistant.delta" in streams
    assert "assistant.final" in streams
