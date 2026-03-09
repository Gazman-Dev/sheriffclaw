from unittest.mock import AsyncMock

import pytest

from services.sheriff_gateway import service as gateway_service
from services.sheriff_gateway.service import SheriffGatewayService


# Mock ProcClient since we can't spawn real processes in unit tests
class MockProcClient:
    def __init__(self, name):
        self.name = name
        self.requests = []

    async def request(self, op, payload, stream_events=False):
        self.requests.append((op, payload))

        # Default mock behavior
        if op == "codex.session.ensure":
            return [], {"result": {"session": {"session_key": payload["session_key"], "thread_id": "thread-1"}}}
        if op == "codex.memory.inbox.append":
            return [], {"result": {"entry": payload}}
        if op == "codex.session.send":
            # Return a stream generator and a future
            async def _stream():
                if False: yield {}  # make it a generator

            fut = AsyncMock()
            return _stream(), fut

        if op == "web.request":
            return [], {"result": {"status": 200, "body": "web-ok"}}

        return [], {"result": {}}


@pytest.mark.asyncio
async def test_gateway_opens_session_and_forwards_message():
    svc = SheriffGatewayService()
    svc.ai = MockProcClient("codex-mcp-host")

    async def ai_stream():
        yield {"event": "assistant.delta", "payload": {"text": "hi"}}

    async def mock_request(op, payload, stream_events=False):
        if op == "codex.session.ensure":
            return [], {"result": {"session": {"session_key": payload["session_key"], "thread_id": "thread-1"}}}
        if op == "codex.session.send":
            return ai_stream(), AsyncMock()
        return [], {"result": {}}

    svc.ai.request = AsyncMock(side_effect=mock_request)
    svc.secrets.request = AsyncMock(
        return_value=([], {"ok": True, "result": {"unlocked": True, "provider": "stub", "api_key": ""}}))

    events = []

    async def emit(e, p):
        events.append((e, p))

    await svc.handle_user_message({
        "channel": "cli",
        "principal_external_id": "u1",
        "text": "hello"
    }, emit, "req-1")

    # Verify events passed through
    assert ("assistant.delta", {"text": "hi"}) in events
    called_ops = [call.args[0] for call in svc.ai.request.call_args_list]
    assert "codex.memory.inbox.append" in called_ops
    assert "codex.task.capture_from_message" not in called_ops
    send_payload = next(call.args[1] for call in svc.ai.request.call_args_list if call.args[0] == "codex.session.send")
    assert send_payload["prompt"] == "hello"


@pytest.mark.asyncio
async def test_gateway_passes_model_ref_to_worker():
    svc = SheriffGatewayService()
    svc.ai = MockProcClient("codex-mcp-host")

    async def ai_stream():
        if False:
            yield {}

    async def mock_ai_request(op, payload, stream_events=False):
        if op == "codex.session.ensure":
            return [], {"result": {"session": {"session_key": payload["session_key"], "thread_id": "thread-1"}}}
        if op == "codex.memory.inbox.append":
            return [], {"result": {"entry": payload}}
        if op == "codex.session.send":
            assert payload["model_ref"] == "test/default"
            assert payload["prompt"] == "hello"
            return ai_stream(), AsyncMock()
        return [], {"result": {}}

    svc.ai.request = AsyncMock(side_effect=mock_ai_request)
    svc.secrets.request = AsyncMock(
        return_value=([], {"ok": True, "result": {"unlocked": True, "provider": "stub", "api_key": ""}}))

    async def emit(e, p):
        return

    await svc.handle_user_message(
        {
            "channel": "cli",
            "principal_external_id": "u1",
            "text": "hello",
            "model_ref": "test/default",
        },
        emit,
        "req-2",
    )


@pytest.mark.asyncio
async def test_gateway_handles_locked_secret_tool_without_crash():
    svc = SheriffGatewayService()
    svc.secrets = MockProcClient("sheriff-secrets")

    async def mock_secret_request(op, payload, stream_events=False):
        return [], {"ok": False, "error": "RuntimeError", "details": {}}

    svc.secrets.request = AsyncMock(side_effect=mock_secret_request)

    out = await svc._route_tool("u1", {"tool_name": "secure.secret.ensure", "payload": {"handle": "gh_token"}})
    assert out["status"] == "needs_secret"
    assert out["handle"] == "gh_token"


@pytest.mark.asyncio
async def test_gateway_locked_vault_returns_error_instead_of_stub_echo():
    svc = SheriffGatewayService()
    svc.ai = MockProcClient("codex-mcp-host")

    async def mock_secrets_request(op, payload, stream_events=False):
        if op == "secrets.is_unlocked":
            return [], {"ok": True, "result": {"unlocked": False}}
        return [], {"ok": False, "error": "secrets are locked", "result": {}}

    svc.secrets.request = AsyncMock(side_effect=mock_secrets_request)

    events = []

    async def emit(e, p):
        events.append((e, p))

    out = await svc.handle_user_message(
        {
            "channel": "cli",
            "principal_external_id": "u1",
            "text": "hello",
        },
        emit,
        "req-locked",
    )

    assert out["status"] == "locked"
    finals = [p for e, p in events if e == "assistant.final"]
    assert finals, "expected assistant.final message"
    assert "vault is locked" in finals[-1]["text"].lower()


@pytest.mark.asyncio
async def test_gateway_unlocks_with_supplied_master_password():
    svc = SheriffGatewayService()
    svc.ai = MockProcClient("codex-mcp-host")

    async def ai_stream():
        yield {"event": "assistant.delta", "payload": {"text": "hi"}}

    async def mock_ai_request(op, payload, stream_events=False):
        if op == "codex.session.ensure":
            return [], {"result": {"session": {"session_key": payload["session_key"], "thread_id": "thread-1"}}}
        if op == "codex.memory.inbox.append":
            return [], {"result": {"entry": payload}}
        if op == "codex.session.send":
            return ai_stream(), AsyncMock()
        return [], {"result": {}}

    svc.ai.request = AsyncMock(side_effect=mock_ai_request)

    state = {"unlocked": False}

    async def mock_secrets_request(op, payload, stream_events=False):
        if op == "secrets.is_unlocked":
            return [], {"ok": True, "result": {"unlocked": state["unlocked"]}}
        if op == "secrets.unlock":
            state["unlocked"] = payload.get("master_password") == "pw"
            return [], {"ok": True, "result": {"ok": state["unlocked"]}}
        if op == "secrets.get_llm_provider":
            return [], {"ok": True, "result": {"provider": "stub"}}
        if op == "secrets.get_llm_api_key":
            return [], {"ok": True, "result": {"api_key": ""}}
        return [], {"ok": True, "result": {}}

    svc.secrets.request = AsyncMock(side_effect=mock_secrets_request)

    events = []

    async def emit(e, p):
        events.append((e, p))

    out = await svc.handle_user_message(
        {
            "channel": "cli",
            "principal_external_id": "u1",
            "text": "hello",
            "master_password": "pw",
        },
        emit,
        "req-unlock",
    )

    assert out["status"] == "done"
    assert ("assistant.delta", {"text": "hi"}) in events


@pytest.mark.asyncio
async def test_gateway_routes_web_tool():
    svc = SheriffGatewayService()
    svc.ai = MockProcClient("codex-mcp-host")
    svc.web = MockProcClient("sheriff-web")

    # Mock AI returning a tool call
    async def ai_stream():
        yield {
            "event": "tool.call",
            "payload": {
                "tool_name": "secure.web.request",
                "payload": {"host": "example.com"}
            }
        }

    async def mock_ai_request(op, payload, stream_events=False):
        if op == "codex.session.ensure":
            return [], {"result": {"session": {"session_key": payload["session_key"], "thread_id": "thread-1"}}}
        if op == "codex.memory.inbox.append":
            return [], {"result": {"entry": payload}}
        if op == "codex.session.send":
            return ai_stream(), AsyncMock()
        # Fallback for tool_result etc
        return [], {"result": {}}

    svc.ai.request = AsyncMock(side_effect=mock_ai_request)
    svc.secrets.request = AsyncMock(
        return_value=([], {"ok": True, "result": {"unlocked": True, "provider": "stub", "api_key": ""}}))

    # Mock Web response
    svc.web.request = AsyncMock(return_value=([], {"result": {"status": 200}}))

    events = []

    async def emit(e, p):
        events.append((e, p))

    await svc.handle_user_message({
        "channel": "cli",
        "principal_external_id": "u1",
        "text": "fetch web"
    }, emit, "req-1")

    # Check that tool result was emitted
    tool_results = [p for e, p in events if e == "tool.result"]
    assert len(tool_results) == 1
    assert tool_results[0]["status"] == 200

    # Check routing to web service
    assert svc.web.request.call_args[0][0] == "web.request"
    assert svc.web.request.call_args[0][1]["host"] == "example.com"


@pytest.mark.asyncio
async def test_gateway_secrets_call_rejects_non_allowlisted_op():
    svc = SheriffGatewayService()
    out = await svc.secrets_call({"op": "secrets.delete_everything", "payload": {}}, None, "r1")
    assert out["ok"] is False
    assert out["error"] == "op_not_allowed"


@pytest.mark.asyncio
async def test_gateway_secrets_call_allows_expected_op():
    svc = SheriffGatewayService()
    svc.secrets.request = AsyncMock(return_value=([], {"ok": True, "result": {"unlocked": True}}))
    out = await svc.secrets_call({"op": "secrets.is_unlocked", "payload": {}}, None, "r2")
    assert out["ok"] is True
    assert out["result"]["unlocked"] is True


@pytest.mark.asyncio
async def test_gateway_maps_codex_auth_error_to_auth_message(monkeypatch):
    svc = SheriffGatewayService()
    svc.ai = MockProcClient("codex-mcp-host")
    monkeypatch.setattr(gateway_service, "codex_auth_help_text", lambda **_: "Run /auth-login.")

    async def ai_stream():
        if False:
            yield {}

    async def mock_ai_request(op, payload, stream_events=False):
        if op == "codex.session.ensure":
            return [], {"result": {"session": {"session_key": payload["session_key"], "thread_id": "thread-1"}}}
        if op == "codex.memory.inbox.append":
            return [], {"result": {"entry": payload}}
        if op == "codex.session.send":
            return ai_stream(), {"ok": False, "error": "401 Unauthorized: Missing bearer or basic authentication"}
        return [], {"result": {}}

    async def mock_secrets_request(op, payload, stream_events=False):
        if op == "secrets.is_unlocked":
            return [], {"ok": True, "result": {"unlocked": True}}
        if op == "secrets.get_llm_provider":
            return [], {"ok": True, "result": {"provider": "openai-codex-chatgpt"}}
        return [], {"ok": True, "result": {}}

    svc.ai.request = AsyncMock(side_effect=mock_ai_request)
    svc.secrets.request = AsyncMock(side_effect=mock_secrets_request)

    events = []

    async def emit(e, p):
        events.append((e, p))

    out = await svc.handle_user_message(
        {"channel": "cli", "principal_external_id": "u1", "text": "hello"},
        emit,
        "req-auth",
    )

    assert out["status"] == "auth_required"
    assert ("assistant.final", {"text": "Run /auth-login."}) in events


@pytest.mark.asyncio
async def test_gateway_sets_default_model_for_chatgpt_provider():
    svc = SheriffGatewayService()
    svc.ai = MockProcClient("codex-mcp-host")

    async def ai_stream():
        if False:
            yield {}

    async def mock_ai_request(op, payload, stream_events=False):
        if op == "codex.session.ensure":
            return [], {"result": {"session": {"session_key": payload["session_key"], "thread_id": "thread-1"}}}
        if op == "codex.memory.inbox.append":
            return [], {"result": {"entry": payload}}
        if op == "codex.session.send":
            assert payload["model_ref"] == "gpt-5-codex"
            return ai_stream(), {"result": {"ok": True, "result": {"content": [{"type": "text", "text": "ok"}]}}}
        return [], {"result": {}}

    async def mock_secrets_request(op, payload, stream_events=False):
        if op == "secrets.is_unlocked":
            return [], {"ok": True, "result": {"unlocked": True}}
        if op == "secrets.get_llm_provider":
            return [], {"ok": True, "result": {"provider": "openai-codex-chatgpt"}}
        return [], {"ok": True, "result": {}}

    svc.ai.request = AsyncMock(side_effect=mock_ai_request)
    svc.secrets.request = AsyncMock(side_effect=mock_secrets_request)

    events = []

    async def emit(e, p):
        events.append((e, p))

    out = await svc.handle_user_message({"channel": "cli", "principal_external_id": "u1", "text": "hello"}, emit, "req-model")

    assert out["status"] == "done"


@pytest.mark.asyncio
async def test_gateway_uses_final_rpc_payload_text_when_no_events():
    svc = SheriffGatewayService()
    svc.ai = MockProcClient("codex-mcp-host")

    async def ai_stream():
        if False:
            yield {}

    async def mock_ai_request(op, payload, stream_events=False):
        if op == "codex.session.ensure":
            return [], {"result": {"session": {"session_key": payload["session_key"], "thread_id": "thread-1"}}}
        if op == "codex.memory.inbox.append":
            return [], {"result": {"entry": payload}}
        if op == "codex.session.send":
            return ai_stream(), {
                "result": {
                    "ok": True,
                    "result": {
                        "structuredContent": {"threadId": "thread-1", "content": ""},
                        "content": [{"type": "text", "text": "hello from final payload"}],
                    },
                }
            }
        return [], {"result": {}}

    svc.ai.request = AsyncMock(side_effect=mock_ai_request)
    svc.secrets.request = AsyncMock(
        return_value=([], {"ok": True, "result": {"unlocked": True, "provider": "stub", "api_key": ""}})
    )

    events = []

    async def emit(e, p):
        events.append((e, p))

    out = await svc.handle_user_message(
        {"channel": "cli", "principal_external_id": "u1", "text": "hello"},
        emit,
        "req-final-text",
    )

    assert out["status"] == "done"
    assert ("assistant.final", {"text": "hello from final payload"}) in events
