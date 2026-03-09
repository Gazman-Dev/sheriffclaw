import argparse

from services.sheriff_ctl import chat


class _DummyProcClient:
    def __init__(self, name):
        self.name = name


def test_cmd_chat_one_shot_auth_login_runs_local_login(monkeypatch, capsys):
    calls = {"wait": 0}

    class _Proc:
        async def request(self, op, payload, stream_events=False):
            return [], {"result": {"kind": "sheriff", "message": "Open https://example.test"}}

    monkeypatch.setattr(chat, "ProcClient", _DummyProcClient)
    monkeypatch.setattr(chat, "ProcClient", lambda name: _Proc())
    monkeypatch.setattr(chat, "_wait_extra_or_esc_until", lambda _: calls.__setitem__("wait", calls["wait"] + 1))

    chat.cmd_chat(argparse.Namespace(principal="main", model_ref=None, one_shot="/auth-login"))

    out = capsys.readouterr().out
    assert calls["wait"] == 1
    assert "https://example.test" in out.lower()
