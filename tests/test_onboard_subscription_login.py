import argparse

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
