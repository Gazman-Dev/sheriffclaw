import pytest
from unittest.mock import AsyncMock
from services.sheriff_tg_gate.service import SheriffTgGateService

@pytest.fixture
def tg_gate_svc(tmp_path, monkeypatch):
    monkeypatch.setattr("services.sheriff_tg_gate.service.gw_root", lambda: tmp_path)
    svc = SheriffTgGateService()
    svc.policy = AsyncMock()
    svc.secrets = AsyncMock()
    return svc

@pytest.mark.asyncio
async def test_gate_applies_callback(tg_gate_svc):
    tg_gate_svc.policy.request.return_value = (None, {"result": {"status": "recorded"}})

    res = await tg_gate_svc.apply_callback({
        "approval_id": "123",
        "action": "allow"
    }, None, "r1")

    assert res["status"] == "recorded"
    tg_gate_svc.policy.request.assert_called_with(
        "policy.apply_callback",
        {"approval_id": "123", "action": "allow"}
    )

@pytest.mark.asyncio
async def test_gate_submits_secret(tg_gate_svc):
    tg_gate_svc.secrets.request.return_value = (None, {"result": {"status": "saved"}})

    res = await tg_gate_svc.submit_secret({
        "handle": "gh",
        "value": "123"
    }, None, "r1")

    assert res["status"] == "saved"
    tg_gate_svc.secrets.request.assert_called_with(
        "secrets.set_secret",
        {"handle": "gh", "value": "123"}
    )

@pytest.mark.asyncio
async def test_gate_logs_requests(tg_gate_svc, tmp_path):
    # Ensure log path exists
    log_file = tmp_path / "state" / "gate_events.jsonl"

    await tg_gate_svc.notify_approval_required({
        "principal_id": "u1",
        "approval_id": "app-1"
    }, None, "r1")

    assert log_file.exists()
    content = log_file.read_text()
    assert '"event": "approval_required"' in content
    assert '"approval_id": "app-1"' in content