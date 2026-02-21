import json
import types

from services.sheriff_ctl import ctl


def test_debug_mode_read_write_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("services.sheriff_ctl.ctl.gw_root", lambda: tmp_path)

    ctl._write_debug_mode(True)
    assert ctl._read_debug_mode() is True

    data = json.loads((tmp_path / "state" / "debug_mode.json").read_text(encoding="utf-8"))
    assert data == {"enabled": True}

    ctl._write_debug_mode(False)
    assert ctl._read_debug_mode() is False


def test_is_onboarded_with_sqlite_state(tmp_path, monkeypatch):
    monkeypatch.setattr("services.sheriff_ctl.ctl.gw_root", lambda: tmp_path)
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "secrets.db").write_text("stub", encoding="utf-8")
    assert ctl._is_onboarded() is True


def test_is_onboarded_false_when_no_state(tmp_path, monkeypatch):
    monkeypatch.setattr("services.sheriff_ctl.ctl.gw_root", lambda: tmp_path)
    assert ctl._is_onboarded() is False


def test_cmd_debug_updates_state(tmp_path, monkeypatch):
    monkeypatch.setattr("services.sheriff_ctl.ctl.gw_root", lambda: tmp_path)
    ctl.cmd_debug(type("A", (), {"value": "on"})())
    assert ctl._read_debug_mode() is True


def test_wait_extra_until_uses_remaining_sleep(monkeypatch):
    monkeypatch.setattr("services.sheriff_ctl.ctl.sys.stdin", types.SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr("services.sheriff_ctl.ctl.time.time", lambda: 100.0)
    captured = {"sleep": None}
    monkeypatch.setattr("services.sheriff_ctl.ctl.time.sleep", lambda s: captured.__setitem__("sleep", s))

    ctl._wait_extra_or_esc_until(106.5)
    assert abs(captured["sleep"] - 6.5) < 1e-6
