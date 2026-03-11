import pytest

from services.sheriff_cli_gate import service as cli_gate_service
from services.sheriff_cli_gate.service import SheriffCliGateService


class FakeRPC:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    async def request(self, op, payload):
        self.calls.append((op, payload))
        if self.responses:
            return self.responses.pop(0)
        return (None, {"result": {}})


@pytest.mark.asyncio
async def test_non_slash_rejected():
    svc = SheriffCliGateService()
    res = await svc.handle_message({"text": "hello"}, None, "r1")
    assert res["kind"] == "error"


@pytest.mark.asyncio
async def test_help_command():
    svc = SheriffCliGateService()
    res = await svc.handle_message({"text": "/help"}, None, "r1")
    assert res["kind"] == "sheriff"
    assert "/status" in res["message"]
    assert "/update" in res["message"]
    assert "/auth-status" in res["message"]


@pytest.mark.asyncio
async def test_secret_command_routes_to_requests():
    svc = SheriffCliGateService()
    svc.requests = FakeRPC(responses=[(None, {"result": {"status": "approved"}})])

    res = await svc.handle_message({"text": "/secret gh_token abc123"}, None, "r1")

    assert res["kind"] == "sheriff"
    assert "approved" in res["message"]
    assert svc.requests.calls == [("requests.resolve_secret", {"key": "gh_token", "value": "abc123"})]


@pytest.mark.asyncio
async def test_allow_tool_command_routes_to_policy_resolution():
    svc = SheriffCliGateService()
    svc.requests = FakeRPC(responses=[(None, {"result": {"status": "approved"}})])

    res = await svc.handle_message({"text": "/allow-tool python"}, None, "r1")

    assert res["kind"] == "sheriff"
    assert "approved" in res["message"]
    assert svc.requests.calls == [("requests.resolve_tool", {"key": "python", "action": "always_allow"})]


@pytest.mark.asyncio
async def test_unlock_command_usage_error():
    svc = SheriffCliGateService()
    res = await svc.handle_message({"text": "/unlock"}, None, "r1")
    assert res["kind"] == "error"
    assert "Usage" in res["message"]


@pytest.mark.asyncio
async def test_unlock_command_success_and_failure():
    svc = SheriffCliGateService()
    svc.secrets = FakeRPC(responses=[
        (None, {"result": {"ok": False}}),
        (None, {"result": {"ok": True}}),
    ])
    svc.requests = FakeRPC(responses=[(None, {"result": {"ok": True}}), (None, {"result": {"ok": True}})])

    bad = await svc.handle_message({"text": "/unlock wrong"}, None, "r1")
    ok = await svc.handle_message({"text": "/unlock right"}, None, "r2")

    assert bad["kind"] == "sheriff" and "failed" in bad["message"].lower()
    assert ok["kind"] == "sheriff" and "unlocked" in ok["message"].lower()
    assert ("secrets.unlock", {"master_password": "right"}) in svc.secrets.calls


@pytest.mark.asyncio
async def test_auth_status_command_when_logged_in(monkeypatch):
    svc = SheriffCliGateService()
    monkeypatch.setattr(
        cli_gate_service,
        "finalize_codex_device_auth",
        lambda: {"available": True, "logged_in": True, "detail": "Logged in."},
    )

    res = await svc.handle_message({"text": "/auth-status"}, None, "r1")

    assert res["kind"] == "sheriff"
    assert "active" in res["message"].lower()


@pytest.mark.asyncio
async def test_auth_status_command_when_logged_out(monkeypatch):
    svc = SheriffCliGateService()
    monkeypatch.setattr(
        cli_gate_service,
        "finalize_codex_device_auth",
        lambda: {"available": True, "logged_in": False, "detail": "Not logged in."},
    )
    monkeypatch.setattr(
        cli_gate_service,
        "codex_device_auth_status",
        lambda: {"active": False, "detail": ""},
    )
    monkeypatch.setattr(
        cli_gate_service,
        "codex_auth_help_text",
        lambda **_: "Run local login.",
    )

    res = await svc.handle_message({"text": "/auth-status"}, None, "r1")

    assert res["kind"] == "sheriff"
    assert "not logged in" in res["message"].lower()
    assert "run local login" in res["message"].lower()


@pytest.mark.asyncio
async def test_auth_login_command_returns_instruction(monkeypatch):
    svc = SheriffCliGateService()
    monkeypatch.setattr(
        cli_gate_service,
        "start_codex_device_auth",
        lambda: {"ok": True, "started": True, "message": "Open https://example.test and enter code TEST-123"},
    )

    res = await svc.handle_message({"text": "/auth-login"}, None, "r1")

    assert res["kind"] == "sheriff"
    assert "https://example.test" in res["message"]


@pytest.mark.asyncio
async def test_update_command_starts_detached_update(monkeypatch, tmp_path):
    monkeypatch.setattr(cli_gate_service, "gw_root", lambda: tmp_path / "gw")
    svc = SheriffCliGateService()
    captured = {}

    class FakeProc:
        pid = 4321

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr(cli_gate_service.subprocess, "Popen", fake_popen)

    res = await svc.handle_message({"text": "/update no-pull force"}, None, "r1")

    assert res["kind"] == "sheriff"
    assert "4321" in res["message"]
    assert "--no-pull" in captured["cmd"]
    assert "--force" in captured["cmd"]
    assert captured["kwargs"]["stdin"] == cli_gate_service.subprocess.DEVNULL


@pytest.mark.asyncio
async def test_update_command_rejects_running_update(monkeypatch, tmp_path):
    monkeypatch.setattr(cli_gate_service, "gw_root", lambda: tmp_path / "gw")
    svc = SheriffCliGateService()
    svc.update_pid_path.parent.mkdir(parents=True, exist_ok=True)
    svc.update_pid_path.write_text("999", encoding="utf-8")
    monkeypatch.setattr(svc, "_is_pid_running", lambda pid: pid == 999)

    res = await svc.handle_message({"text": "/update"}, None, "r1")

    assert res["kind"] == "sheriff"
    assert "already running" in res["message"].lower()
