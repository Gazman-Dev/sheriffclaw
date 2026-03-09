# File: tests/test_sheriff_entry.py

import argparse

from services.sheriff_ctl import chat, ctl


def test_main_sheriff_debug_sets_env_and_runs_status(monkeypatch):
    called = {"status": 0}
    monkeypatch.setattr(ctl, "cmd_status", lambda args: called.__setitem__("status", called["status"] + 1))

    ctl.main_sheriff(["--debug", "status"])
    assert called["status"] == 1


def test_main_sheriff_message_routes_to_cmd_entry(monkeypatch):
    called = {}

    def fake_cmd_entry(args):
        called["message"] = args.message

    monkeypatch.setattr(ctl, "cmd_entry", fake_cmd_entry)
    monkeypatch.setattr(ctl, "cmd_debug",
                        lambda args: (_ for _ in ()).throw(AssertionError("cmd_debug should not be called")))

    ctl.main_sheriff(["hello", "world"])
    assert called["message"] == ["hello", "world"]


def test_cmd_entry_one_shot_message_routes_to_chat(monkeypatch):
    called = {}

    def fake_chat(args):
        called["principal"] = args.principal
        called["one_shot"] = args.one_shot

    monkeypatch.setattr(chat, "cmd_chat", fake_chat)
    chat.cmd_entry(argparse.Namespace(message=["hello", "there"]))
    assert called["principal"] == "main"
    assert called["one_shot"] == "hello there"


def test_cmd_entry_one_shot_slash_routes_to_chat(monkeypatch):
    called = {}

    def fake_chat(args):
        called["principal"] = args.principal
        called["one_shot"] = args.one_shot

    monkeypatch.setattr(chat, "cmd_chat", fake_chat)
    chat.cmd_entry(argparse.Namespace(message=["/status"]))
    assert called["principal"] == "main"
    assert called["one_shot"] == "/status"


def test_cmd_entry_not_onboarded_runs_onboard(monkeypatch):
    called = {}
    monkeypatch.setattr(chat, "_is_onboarded", lambda: False)

    def fake_onboard(args):
        called["keep_unchanged"] = args.keep_unchanged

    monkeypatch.setattr(chat, "cmd_onboard", fake_onboard)

    chat.cmd_entry(argparse.Namespace(message=[]))
    assert called["keep_unchanged"] is False


def test_cmd_entry_no_args_starts_chat_when_onboarded(monkeypatch):
    monkeypatch.setattr(chat, "_is_onboarded", lambda: True)
    called = {}
    def fake_chat(args):
        called["principal"] = args.principal
        called["one_shot"] = args.one_shot

    monkeypatch.setattr(chat, "cmd_chat", fake_chat)

    chat.cmd_entry(argparse.Namespace(message=[]))
    assert called["principal"] == "main"
    assert called["one_shot"] is None
