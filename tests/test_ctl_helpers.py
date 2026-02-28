# File: tests/test_ctl_helpers.py

import json
import types

from services.sheriff_ctl import system, utils


def test_debug_mode_read_write_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "gw_root", lambda: tmp_path)

    utils._write_debug_mode(True)
    assert utils._read_debug_mode() is True

    data = json.loads((tmp_path / "state" / "debug_mode.json").read_text(encoding="utf-8"))
    assert data == {"enabled": True}

    utils._write_debug_mode(False)
    assert utils._read_debug_mode() is False


def test_is_onboarded_with_sqlite_state(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "gw_root", lambda: tmp_path)
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "secrets.db").write_text("stub", encoding="utf-8")
    assert utils._is_onboarded() is True


def test_is_onboarded_false_when_no_state(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "gw_root", lambda: tmp_path)
    assert utils._is_onboarded() is False


def test_cmd_debug_updates_state(tmp_path, monkeypatch):
    monkeypatch.setattr(system, "_write_debug_mode", utils._write_debug_mode)
    monkeypatch.setattr(utils, "gw_root", lambda: tmp_path)
    system.cmd_debug(type("A", (), {"debug_args": ["on"]})())
    assert utils._read_debug_mode() is True


def test_wait_extra_until_uses_remaining_sleep(monkeypatch):
    monkeypatch.setattr(utils.sys, "stdin", types.SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(utils.time, "time", lambda: 100.0)
    captured = {"sleep": None}
    monkeypatch.setattr(utils.time, "sleep", lambda s: captured.__setitem__("sleep", s))

    utils._wait_extra_or_esc_until(106.5)
    assert abs(captured["sleep"] - 6.5) < 1e-6