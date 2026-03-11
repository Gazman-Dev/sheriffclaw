from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.telegram_listener.service import TelegramListenerService
from shared.errors import ServiceCrashedError


@pytest.mark.asyncio
async def test_handle_ai_message_passes_session_metadata_to_gateway(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    svc = TelegramListenerService()
    svc._send_message = lambda token, chat_id, text: None

    async def fake_secrets(op: str, payload: dict):
        if op == "secrets.is_unlocked":
            return {"unlocked": True}
        if op == "secrets.activation.status":
            return {"user_id": "u1"}
        return {}

    async def fake_stream():
        yield {"event": "assistant.final", "payload": {"text": "ok"}}

    svc._secrets = fake_secrets
    svc.gateway.request = AsyncMock(return_value=(fake_stream(), {"result": {"status": "done"}}))

    await svc._handle_ai_message(
        "llm-token",
        "sheriff-token",
        "u1",
        123,
        "hello",
        chat_type="supergroup",
        message_thread_id=77,
    )

    op, payload = svc.gateway.request.call_args.args[:2]
    assert op == "gateway.handle_user_message"
    assert payload["chat_id"] == 123
    assert payload["chat_type"] == "supergroup"
    assert payload["message_thread_id"] == 77


@pytest.mark.asyncio
async def test_poll_bot_extracts_topic_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    svc = TelegramListenerService()
    svc._ensure_long_polling = lambda token: None

    class FakeResp:
        status_code = 200

        def json(self):
            return {
                "ok": True,
                "result": [
                    {
                        "update_id": 1,
                        "message": {
                            "from": {"id": 42},
                            "chat": {"id": -100, "type": "supergroup"},
                            "message_thread_id": 9,
                            "text": "hello topic",
                        },
                    }
                ],
            }

    captured = []

    async def fake_handle_ai_message(token, sheriff_token, user_id, chat_id, text, *, chat_type="", message_thread_id=None):
        captured.append((token, sheriff_token, user_id, chat_id, text, chat_type, message_thread_id))

    svc._http_get = lambda url, params, timeout: FakeResp()
    svc._handle_ai_message = fake_handle_ai_message

    original_create_task = __import__("asyncio").create_task

    def _run_now(coro):
        return original_create_task(coro)

    monkeypatch.setattr("asyncio.create_task", _run_now)

    offsets = {"llm": 0}
    await svc._poll_bot("llm", "llm-token", "sheriff-token", offsets)
    await __import__("asyncio").sleep(0)

    assert captured == [("llm-token", "sheriff-token", "42", -100, "hello topic", "supergroup", 9)]
    assert offsets["llm"] == 2


@pytest.mark.asyncio
async def test_handle_ai_message_timeout_surfaces_user_message(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    svc = TelegramListenerService()
    sent = []
    svc._send_message = lambda token, chat_id, text: sent.append((token, chat_id, text))

    async def fake_secrets(op: str, payload: dict):
        if op == "secrets.is_unlocked":
            return {"unlocked": True}
        if op == "secrets.activation.status":
            return {"user_id": "u1"}
        return {}

    svc._secrets = fake_secrets
    svc.gateway.request = AsyncMock(side_effect=ServiceCrashedError("rpc timeout waiting for sheriff-gateway"))

    await svc._handle_ai_message("llm-token", "sheriff-token", "u1", 123, "hello")

    assert sent
    assert "timed out" in sent[-1][2].lower()
