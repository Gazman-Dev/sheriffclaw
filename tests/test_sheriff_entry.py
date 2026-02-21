import argparse

from services.sheriff_ctl import ctl


def test_main_sheriff_debug_routes_to_cmd_debug(monkeypatch):
    called = {}

    def fake_cmd_debug(args):
        called["value"] = args.value

    monkeypatch.setattr(ctl, "cmd_debug", fake_cmd_debug)
    monkeypatch.setattr(ctl, "cmd_entry", lambda args: (_ for _ in ()).throw(AssertionError("cmd_entry should not be called")))

    ctl.main_sheriff(["--debug", "on"])
    assert called["value"] == "on"


def test_main_sheriff_message_routes_to_cmd_entry(monkeypatch):
    called = {}

    def fake_cmd_entry(args):
        called["message"] = args.message

    monkeypatch.setattr(ctl, "cmd_entry", fake_cmd_entry)
    monkeypatch.setattr(ctl, "cmd_debug", lambda args: (_ for _ in ()).throw(AssertionError("cmd_debug should not be called")))

    ctl.main_sheriff(["hello", "world"])
    assert called["message"] == ["hello", "world"]


def test_cmd_entry_not_onboarded_runs_onboard(monkeypatch):
    called = {}
    monkeypatch.setattr(ctl, "_is_onboarded", lambda: False)

    def fake_onboard(args):
        called["keep_unchanged"] = args.keep_unchanged

    monkeypatch.setattr(ctl, "cmd_onboard", fake_onboard)

    ctl.cmd_entry(argparse.Namespace(message=[]))
    assert called["keep_unchanged"] is False


def test_cmd_entry_menu_onboard_keep_yes(monkeypatch):
    monkeypatch.setattr(ctl, "_is_onboarded", lambda: True)
    answers = iter(["onboard", ""])  # default yes
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    called = {}

    def fake_onboard(args):
        called["keep_unchanged"] = args.keep_unchanged

    monkeypatch.setattr(ctl, "cmd_onboard", fake_onboard)

    ctl.cmd_entry(argparse.Namespace(message=[]))
    assert called["keep_unchanged"] is True


def test_cmd_entry_menu_onboard_keep_no(monkeypatch):
    monkeypatch.setattr(ctl, "_is_onboarded", lambda: True)
    answers = iter(["onboard", "n"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    called = {}

    def fake_onboard(args):
        called["keep_unchanged"] = args.keep_unchanged

    monkeypatch.setattr(ctl, "cmd_onboard", fake_onboard)

    ctl.cmd_entry(argparse.Namespace(message=[]))
    assert called["keep_unchanged"] is False


def test_cmd_entry_menu_restart_bad_password(monkeypatch):
    monkeypatch.setattr(ctl, "_is_onboarded", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "restart")
    monkeypatch.setattr("getpass.getpass", lambda _: "bad")
    monkeypatch.setattr(ctl, "_verify_master_password", lambda mp: False)

    called = {"stop": 0, "start": 0}
    monkeypatch.setattr(ctl, "cmd_stop", lambda args: called.__setitem__("stop", called["stop"] + 1))
    monkeypatch.setattr(ctl, "cmd_start", lambda args: called.__setitem__("start", called["start"] + 1))

    ctl.cmd_entry(argparse.Namespace(message=[]))
    assert called["stop"] == 0
    assert called["start"] == 0


def test_cmd_entry_menu_restart_good_password(monkeypatch):
    monkeypatch.setattr(ctl, "_is_onboarded", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "restart")
    monkeypatch.setattr("getpass.getpass", lambda _: "good")
    monkeypatch.setattr(ctl, "_verify_master_password", lambda mp: True)

    called = {"stop": 0, "start": 0}
    monkeypatch.setattr(ctl, "cmd_stop", lambda args: called.__setitem__("stop", called["stop"] + 1))
    monkeypatch.setattr(ctl, "cmd_start", lambda args: called.__setitem__("start", called["start"] + 1))

    ctl.cmd_entry(argparse.Namespace(message=[]))
    assert called["stop"] == 1
    assert called["start"] == 1


def test_cmd_entry_menu_update(monkeypatch):
    monkeypatch.setattr(ctl, "_is_onboarded", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "update")
    called = {"update": 0}
    monkeypatch.setattr(ctl, "cmd_update", lambda args: called.__setitem__("update", called["update"] + 1))

    ctl.cmd_entry(argparse.Namespace(message=[]))
    assert called["update"] == 1


def test_cmd_entry_menu_factory_reset(monkeypatch):
    monkeypatch.setattr(ctl, "_is_onboarded", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "factory reset")
    called = {"reinstall": 0}

    def fake_reinstall(args):
        called["reinstall"] += 1
        assert args.yes is False

    monkeypatch.setattr(ctl, "cmd_reinstall", fake_reinstall)

    ctl.cmd_entry(argparse.Namespace(message=[]))
    assert called["reinstall"] == 1
