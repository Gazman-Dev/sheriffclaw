import argparse

from services.sheriff_ctl import chat


class _DummyProcClient:
    def __init__(self, name):
        self.name = name


def test_cmd_chat_one_shot_auth_login_runs_local_login(monkeypatch, capsys):
    calls = {"login": 0, "wait": 0}
    statuses = iter(
        [
            {"available": True, "logged_in": False, "detail": "Not logged in."},
            {"available": True, "logged_in": True, "detail": "Logged in."},
        ]
    )

    class _Proc:
        returncode = 0

    monkeypatch.setattr(chat, "ProcClient", _DummyProcClient)
    monkeypatch.setattr(chat, "codex_auth_status", lambda: next(statuses))
    monkeypatch.setattr(chat, "_wait_extra_or_esc_until", lambda _: calls.__setitem__("wait", calls["wait"] + 1))
    monkeypatch.setattr(
        chat.subprocess,
        "run",
        lambda *args, **kwargs: calls.__setitem__("login", calls["login"] + 1) or _Proc(),
    )

    chat.cmd_chat(argparse.Namespace(principal="main", model_ref=None, one_shot="/auth-login"))

    out = capsys.readouterr().out
    assert calls["login"] == 1
    assert calls["wait"] == 1
    assert "starting local codex login" in out.lower()
    assert "auth is now active" in out.lower()
