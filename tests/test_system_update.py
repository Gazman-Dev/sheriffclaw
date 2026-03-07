from __future__ import annotations

import argparse

from services.sheriff_ctl import system


def test_cmd_update_closes_proc_clients(monkeypatch):
    closed = []

    class FakeClient:
        def __init__(self, name: str, *args, **kwargs):
            self.name = name

        async def request(self, op, payload, stream_events=False):
            if self.name == "sheriff-updater" and op == "updater.plan":
                return [], {"result": {"needs_master_password": False}}
            if self.name == "sheriff-gateway" and op == "gateway.queue.status":
                return [], {"result": {"processing": 0}}
            if self.name == "sheriff-updater" and op == "updater.run":
                return [], {"result": {"ok": True, "plan": {"changes": {"secrets": {"increased": False}}}}}
            return [], {"result": {}}

        async def close(self):
            closed.append(self.name)

    monkeypatch.setattr(system, "ProcClient", FakeClient)
    monkeypatch.setattr(system, "_notify_sheriff_channel", lambda text: False)
    monkeypatch.setattr(system, "cmd_stop", lambda args: None)
    monkeypatch.setattr(system, "cmd_start", lambda args: None)
    monkeypatch.setattr(system.subprocess, "run", lambda *args, **kwargs: None)

    system.cmd_update(argparse.Namespace(master_password=None, no_pull=False, force=False))

    assert closed.count("sheriff-gateway") == 1
    assert closed.count("sheriff-updater") == 1
