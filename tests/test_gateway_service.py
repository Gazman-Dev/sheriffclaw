import pytest
from unittest.mock import MagicMock, AsyncMock
from services.sheriff_gateway.service import SheriffGatewayService

# Mock ProcClient since we can't spawn real processes in unit tests
class MockProcClient:
    def __init__(self, name):
        self.name = name
        self.requests = []

    async def request(self, op, payload, stream_events=False):
        self.requests.append((op, payload))

        # Default mock behavior
        if op == "agent.session.open":
            # FIXED: Returns (events, frame) for non-streaming calls
            return [], {"result": {"session_handle": "sess-1"}}

        if op == "agent.session.user_message":
            # Return a stream generator and a future
            async def _stream():
                if False: yield {} # make it a generator
            fut = AsyncMock()
            return _stream(), fut

        if op == "web.request":
            return [], {"result": {"status": 200, "body": "web-ok"}}

        return [], {"result": {}}

@pytest.mark.asyncio
async def test_gateway_opens_session_and_forwards_message():
    svc = SheriffGatewayService()
    svc.ai = MockProcClient("ai-worker")

    # Mock the streaming response from AI
    # We need to handle 'agent.session.open' AND 'agent.session.user_message'

    async def ai_stream():
        yield {"event": "assistant.delta", "payload": {"text": "hi"}}

    async def mock_request(op, payload, stream_events=False):
        if op == "agent.session.open":
            return [], {"result": {"session_handle": "sess-1"}}
        if op == "agent.session.user_message":
            return ai_stream(), AsyncMock()
        return [], {"result": {}}

    svc.ai.request = AsyncMock(side_effect=mock_request)
    svc.secrets.request = AsyncMock(return_value=([], {"ok": True, "result": {"unlocked": True, "provider": "stub", "api_key": ""}}))

    events = []
    async def emit(e, p): events.append((e,p))

    await svc.handle_user_message({
        "channel": "cli",
        "principal_external_id": "u1",
        "text": "hello"
    }, emit, "req-1")

    # Verify events passed through
    assert ("assistant.delta", {"text": "hi"}) in events

@pytest.mark.asyncio
async def test_gateway_passes_model_ref_to_worker():
    svc = SheriffGatewayService()
    svc.ai = MockProcClient("ai-worker")

    async def ai_stream():
        if False:
            yield {}

    async def mock_ai_request(op, payload, stream_events=False):
        if op == "agent.session.open":
            return [], {"result": {"session_handle": "sess-1"}}
        if op == "agent.session.user_message":
            assert payload["model_ref"] == "test/default"
            return ai_stream(), AsyncMock()
        return [], {"result": {}}

    svc.ai.request = AsyncMock(side_effect=mock_ai_request)

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
    svc.ai = MockProcClient("ai-worker")

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
async def test_gateway_routes_web_tool():
    svc = SheriffGatewayService()
    svc.ai = MockProcClient("ai-worker")
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
        if op == "agent.session.open":
            return [], {"result": {"session_handle": "sess-1"}}
        if op == "agent.session.user_message":
            return ai_stream(), AsyncMock()
        # Fallback for tool_result etc
        return [], {"result": {}}

    svc.ai.request = AsyncMock(side_effect=mock_ai_request)
    svc.secrets.request = AsyncMock(return_value=([], {"ok": True, "result": {"unlocked": True, "provider": "stub", "api_key": ""}}))

    # Mock Web response
    svc.web.request = AsyncMock(return_value=([], {"result": {"status": 200}}))

    events = []
    async def emit(e, p): events.append((e,p))

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