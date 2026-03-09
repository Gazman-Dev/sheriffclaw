from __future__ import annotations

import argparse

from services.sheriff_ctl import service_runner


def test_cmd_start_closes_gateway_proc_client(monkeypatch):
    closed = []

    class FakeClient:
        def __init__(self, name: str, *args, **kwargs):
            self.name = name

        async def request(self, op, payload, stream_events=False):
            if op == "health":
                return [], {"result": {"status": "ok"}}
            if op == "secrets.is_unlocked":
                return [], {"result": {"unlocked": True}}
            return [], {"result": {"status": "ok"}}

        async def close(self):
            closed.append(self.name)

    monkeypatch.setattr(service_runner, "ProcClient", FakeClient)
    monkeypatch.setattr(service_runner.SERVICE_MANAGER, "stop_many", lambda services: {})
    monkeypatch.setattr(service_runner.SERVICE_MANAGER, "start", lambda service: "started")
    monkeypatch.setattr(service_runner, "_wait_service_health", lambda service, timeout_sec=10.0: service_runner.asyncio.sleep(0))
    monkeypatch.setattr(service_runner, "_notify_sheriff_channel", lambda text: False)

    service_runner.cmd_start(argparse.Namespace(master_password=None))

    assert closed == ["sheriff-secrets"]


def test_managed_services_include_persistent_agent_path():
    assert "sheriff-gateway" in service_runner.MANAGED_SERVICES
    assert "codex-mcp-host" in service_runner.MANAGED_SERVICES
    assert "sheriff-chat-proxy" in service_runner.MANAGED_SERVICES


def test_gateway_starts_before_requests():
    assert service_runner.GW_ORDER.index("sheriff-gateway") < service_runner.GW_ORDER.index("sheriff-requests")


def test_service_env_sets_install_root(monkeypatch, tmp_path):
    monkeypatch.delenv("SHERIFFCLAW_ROOT", raising=False)
    monkeypatch.setattr(service_runner, "base_root", lambda: tmp_path)
    env = service_runner._service_env("sheriff-updater")
    assert env["SHERIFFCLAW_ROOT"] == str(tmp_path)
