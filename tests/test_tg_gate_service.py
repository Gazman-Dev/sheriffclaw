import pytest

from services.sheriff_tg_gate.service import SheriffTgGateService


class FakeRPC:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    async def request(self, op, payload):
        self.calls.append((op, payload))
        if self.responses:
            return self.responses.pop(0)
        return (None, {"result": {}})


@pytest.fixture
def tg_gate_svc(tmp_path, monkeypatch):
    monkeypatch.setattr("services.sheriff_tg_gate.service.gw_root", lambda: tmp_path)
    svc = SheriffTgGateService()
    svc.policy = FakeRPC()
    svc.gateway = FakeRPC()
    return svc


@pytest.mark.asyncio
async def test_gate_applies_callback(tg_gate_svc):
    tg_gate_svc.policy = FakeRPC(responses=[(None, {"result": {"status": "recorded"}})])

    res = await tg_gate_svc.apply_callback({
        "approval_id": "123",
        "action": "allow"
    }, None, "r1")

    assert res["status"] == "recorded"
    assert tg_gate_svc.policy.calls == [("policy.apply_callback", {"approval_id": "123", "action": "allow"})]


@pytest.mark.asyncio
async def test_gate_submits_secret(tg_gate_svc):
    tg_gate_svc.gateway = FakeRPC(responses=[(None, {"result": {"status": "saved"}})])

    res = await tg_gate_svc.submit_secret({
        "handle": "gh",
        "value": "123"
    }, None, "r1")

    assert res["status"] == "saved"
    assert tg_gate_svc.gateway.calls == [
        ("gateway.secrets.call", {"op": "secrets.set_secret", "payload": {"handle": "gh", "value": "123"}})]


@pytest.mark.asyncio
async def test_gate_logs_requests(tg_gate_svc, tmp_path):
    log_file = tmp_path / "state" / "gate_events.jsonl"

    tg_gate_svc.gateway = FakeRPC(
        responses=[
            (None, {"result": {"token": ""}}),
            (None, {"result": {"user_id": ""}}),
        ]
    )

    await tg_gate_svc.notify_request({
        "type": "action",
        "key": "requests.foo",
        "one_liner": "needs approval",
    }, None, "r1")

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert '"type": "action"' in content
    assert '"key": "requests.foo"' in content
