from __future__ import annotations

import argparse

from services.sheriff_ctl import service_runner


def test_cmd_start_closes_gateway_proc_client(monkeypatch):
    closed = []

    class FakeClient:
        def __init__(self, name: str, *args, **kwargs):
            self.name = name

        async def request(self, op, payload, stream_events=False):
            return [], {"result": {"status": "ok"}}

        async def close(self):
            closed.append(self.name)

    monkeypatch.setattr(service_runner, "ProcClient", FakeClient)
    monkeypatch.setattr(service_runner.SERVICE_MANAGER, "stop_many", lambda services: {})
    monkeypatch.setattr(service_runner.SERVICE_MANAGER, "start_many", lambda services: {})
    monkeypatch.setattr(service_runner, "_gw_secrets_call", lambda op, payload, gw=None: service_runner.asyncio.sleep(0, result={"unlocked": True}))
    monkeypatch.setattr(service_runner, "_notify_sheriff_channel", lambda text: False)

    service_runner.cmd_start(argparse.Namespace(master_password=None))

    assert closed == ["sheriff-gateway"]


def test_managed_services_include_persistent_agent_path():
    assert "sheriff-gateway" in service_runner.MANAGED_SERVICES
    assert "ai-worker" in service_runner.MANAGED_SERVICES
    assert "sheriff-chat-proxy" in service_runner.MANAGED_SERVICES
