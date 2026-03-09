import argparse
import builtins

from services.sheriff_ctl import onboard


def test_cmd_onboard_chatgpt_provider_does_not_abort_for_codex_login(monkeypatch):
    ran = {"async": 0, "start": 0}

    def fake_asyncio_run(coro):
        ran["async"] += 1
        coro.close()
        return True

    monkeypatch.setattr(onboard.asyncio, "run", fake_asyncio_run)
    monkeypatch.setattr(
        onboard.SERVICE_MANAGER,
        "start_many",
        lambda _: ran.__setitem__("start", ran["start"] + 1),
    )
    monkeypatch.setattr(onboard.SERVICE_MANAGER, "start", lambda _: None)
    monkeypatch.setattr(onboard, "_wait_service_health", lambda service: _fake_coro())

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

    assert ran["async"] == 2
    assert ran["start"] == 1


def test_cmd_onboard_defaults_to_chatgpt_provider(monkeypatch, capsys):
    monkeypatch.setattr(onboard, "_is_onboarded", lambda: False)
    monkeypatch.setattr(onboard.getpass, "getpass", lambda prompt="": "mp")

    answers = iter(["", "", ""])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))

    async def fake_run():
        return None

    def fake_asyncio_run(coro):
        coro.close()
        return True

    monkeypatch.setattr(onboard.asyncio, "run", fake_asyncio_run)
    monkeypatch.setattr(onboard.SERVICE_MANAGER, "start", lambda _: None)
    monkeypatch.setattr(onboard.SERVICE_MANAGER, "start_many", lambda _: None)
    monkeypatch.setattr(onboard, "_wait_service_health", lambda service: _fake_coro())

    args = argparse.Namespace(
        master_password=None,
        llm_provider=None,
        llm_api_key=None,
        llm_bot_token="",
        gate_bot_token="",
        keep_unchanged=False,
        allow_telegram=False,
        deny_telegram=True,
    )

    onboard.cmd_onboard(args)

    out = capsys.readouterr().out
    assert "Using default LLM: OpenAI Codex (ChatGPT subscription login via Codex MCP repo)." in out


async def _fake_coro():
    return None
