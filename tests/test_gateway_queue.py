import asyncio

import pytest

from services.sheriff_gateway.service import SheriffGatewayService


@pytest.mark.asyncio
async def test_queue_pause_status():
    svc = SheriffGatewayService()
    out = await svc.queue_control({"pause": True, "reason": "update"}, None, "r1")
    assert out["paused"] is True

    st = await svc.queue_status({}, None, "r2")
    assert st["paused"] is True
    assert st["pause_reason"] == "update"

    out2 = await svc.queue_control({"pause": False}, None, "r3")
    assert out2["paused"] is False


@pytest.mark.asyncio
async def test_handle_user_message_queues_when_paused(monkeypatch):
    svc = SheriffGatewayService()

    async def fake_process(principal_id, payload, emit_event):
        return {"status": "done", "session_handle": "s1"}

    monkeypatch.setattr(svc, "_process_message", fake_process)

    await svc.queue_control({"pause": True, "reason": "update"}, None, "r1")

    task = asyncio.create_task(svc.handle_user_message({"channel": "cli", "principal_external_id": "u1", "text": "hi"}, None, "r2"))
    await asyncio.sleep(0.1)
    st = await svc.queue_status({}, None, "r3")
    assert st["pending"] >= 1

    await svc.queue_control({"pause": False}, None, "r4")
    out = await task
    assert out["status"] == "done"
