import json

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
