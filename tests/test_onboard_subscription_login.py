import argparse

from services.sheriff_ctl import onboard


def test_ensure_codex_subscription_login_already_logged_in(monkeypatch):
    calls = []

    class _Proc:
        def __init__(self, returncode):
            self.returncode = returncode

    def fake_run(argv, env=None, check=False):
        calls.append(list(argv))
        return _Proc(0)

    monkeypatch.setattr(onboard.subprocess, "run", fake_run)

    assert onboard._ensure_codex_subscription_login() is True
    assert calls == [["codex", "login", "status"]]


def test_ensure_codex_subscription_login_runs_login_when_needed(monkeypatch):
    calls = []
    results = iter([1, 0, 0])  # status(not logged), login(ok), status(logged)

    class _Proc:
        def __init__(self, returncode):
            self.returncode = returncode

    def fake_run(argv, env=None, check=False):
        calls.append(list(argv))
        return _Proc(next(results))

    monkeypatch.setattr(onboard.subprocess, "run", fake_run)

    assert onboard._ensure_codex_subscription_login() is True
    assert calls == [
        ["codex", "login", "status"],
        ["codex", "login"],
        ["codex", "login", "status"],
    ]


def test_ensure_codex_subscription_login_fails_if_login_fails(monkeypatch):
    calls = []
    results = iter([1, 1])  # status(not logged), login(fails)

    class _Proc:
        def __init__(self, returncode):
            self.returncode = returncode

    def fake_run(argv, env=None, check=False):
        calls.append(list(argv))
        return _Proc(next(results))

    monkeypatch.setattr(onboard.subprocess, "run", fake_run)

    assert onboard._ensure_codex_subscription_login() is False
    assert calls == [
        ["codex", "login", "status"],
        ["codex", "login"],
    ]


def test_cmd_onboard_aborts_when_subscription_not_logged_in(monkeypatch):
    monkeypatch.setattr(onboard, "_ensure_codex_subscription_login", lambda: False)
    monkeypatch.setattr(onboard.asyncio, "run", lambda _: (_ for _ in ()).throw(AssertionError("asyncio.run must not be reached")))

    start_calls = {"count": 0}
    monkeypatch.setattr(
        onboard.SERVICE_MANAGER,
        "start_many",
        lambda _: start_calls.__setitem__("count", start_calls["count"] + 1),
    )

    args = argparse.Namespace(
        master_password="mp",
        llm_provider="openai-codex-chatgpt",
        llm_api_key="",
        llm_bot_token="",
        gate_bot_token="",
        keep_unchanged=False,
        allow_telegram=False,
        deny_telegram=True,
    )

    onboard.cmd_onboard(args)
    assert start_calls["count"] == 0
