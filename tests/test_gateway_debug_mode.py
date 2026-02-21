import json

from services.sheriff_gateway.service import SheriffGatewayService


class _DummyProc:
    async def request(self, *args, **kwargs):
        raise AssertionError("ai/secrets proc should not be called in these unit tests")


def _make_service_without_init():
    svc = SheriffGatewayService.__new__(SheriffGatewayService)
    svc.ai = _DummyProc()
    svc.web = _DummyProc()
    svc.tools = _DummyProc()
    svc.secrets = _DummyProc()
    svc.requests = _DummyProc()
    svc.tg_gate = _DummyProc()
    svc.sessions = {}
    return svc


def test_debug_mode_enabled_reads_file(tmp_path, monkeypatch):
    svc = _make_service_without_init()
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "debug_mode.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")

    monkeypatch.setattr("services.sheriff_gateway.service.gw_root", lambda: tmp_path)

    assert svc._debug_mode_enabled() is True


def test_debug_mode_disabled_when_missing(tmp_path, monkeypatch):
    svc = _make_service_without_init()
    monkeypatch.setattr("services.sheriff_gateway.service.gw_root", lambda: tmp_path)
    assert svc._debug_mode_enabled() is False


def test_pop_debug_message_fifo(tmp_path, monkeypatch):
    svc = _make_service_without_init()
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    p = state / "debug.agent.jsonl"
    p.write_text('{"text":"first"}\n{"text":"second"}\n', encoding="utf-8")

    monkeypatch.setattr("services.sheriff_gateway.service.gw_root", lambda: tmp_path)

    first = svc._pop_debug_message()
    assert first["text"] == "first"
    remaining = p.read_text(encoding="utf-8").strip().splitlines()
    assert remaining == ['{"text":"second"}']


def test_pop_debug_message_empty_raises(tmp_path, monkeypatch):
    svc = _make_service_without_init()
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "debug.agent.jsonl").write_text("", encoding="utf-8")

    monkeypatch.setattr("services.sheriff_gateway.service.gw_root", lambda: tmp_path)

    try:
        svc._pop_debug_message()
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "empty" in str(e)
