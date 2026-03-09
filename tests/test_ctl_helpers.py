import types

from services.sheriff_ctl import system, utils


def test_is_onboarded_with_sqlite_state(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "gw_root", lambda: tmp_path)
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "secrets.db").write_text("stub", encoding="utf-8")
    assert utils._is_onboarded() is True


def test_is_onboarded_false_when_no_state(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "gw_root", lambda: tmp_path)
    assert utils._is_onboarded() is False


def test_cmd_debug_without_args_prints_usage(capsys):
    system.cmd_debug(type("A", (), {"debug_args": []})())
    out = capsys.readouterr().out
    assert "Usage: sheriff debug" in out


def test_cmd_debug_auto_enables_env(monkeypatch):
    monkeypatch.delenv("SHERIFF_DEBUG", raising=False)
    system.cmd_debug(type("A", (), {"debug_args": []})())
    assert system.os.environ.get("SHERIFF_DEBUG") == "1"


def test_wait_extra_until_uses_remaining_sleep(monkeypatch):
    monkeypatch.setattr(utils.sys, "stdin", types.SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(utils.time, "time", lambda: 100.0)
    captured = {"sleep": None}
    monkeypatch.setattr(utils.time, "sleep", lambda s: captured.__setitem__("sleep", s))

    utils._wait_extra_or_esc_until(106.5)
    assert abs(captured["sleep"] - 6.5) < 1e-6
