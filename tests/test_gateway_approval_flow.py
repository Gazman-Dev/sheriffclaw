import pytest
from unittest.mock import AsyncMock
from services.sheriff_gateway.service import SheriffGatewayService

@pytest.mark.asyncio
async def test_gateway_routes_approval_request_to_gate():
    svc = SheriffGatewayService()
    svc.ai = AsyncMock()
    svc.tg_gate = AsyncMock()

    # AI returns tool call -> Gateway calls Tool -> Tool returns approval_requested

    # Mock the tool route method
    svc._route_tool = AsyncMock(return_value={
        "status": "approval_requested",
        "approval_id": "123",
        "resource": {"type": "tool", "value": "exec"}
    })

    # Mock AI stream
    async def ai_stream():
        yield {
            "event": "tool.call",
            "payload": {"tool_name": "tools.exec", "payload": {}}
        }

    # FIXED: Handle agent.session.open which expects (events, frame)
    # AND agent.session.user_message which expects (stream, fut)
    async def mock_ai_request(op, payload, stream_events=False):
        if op == "agent.session.open":
            return [], {"result": {"session_handle": "s1"}}
        return ai_stream(), AsyncMock()

    svc.ai.request.side_effect = mock_ai_request

    # Call
    res = await svc.handle_user_message({
        "channel": "cli",
        "principal_external_id": "u1",
        "text": "run unsafe"
    }, AsyncMock(), "r1")

    # Assert
    assert res["status"] == "approval_requested"

    # Check that TG Gate was notified
    svc.tg_gate.request.assert_called_with(
        "gate.notify_approval_required",
        {
            "principal_id": "cli:u1",
            "approval_id": "123",
            "context": {"status": "approval_requested", "approval_id": "123", "resource": {"type": "tool", "value": "exec"}}
        }
    )

@pytest.mark.asyncio
async def test_gateway_handles_secret_request():
    svc = SheriffGatewayService()
    svc.ai = AsyncMock()
    svc.tg_gate = AsyncMock()
    svc.secrets = AsyncMock()

    # Mock secrets.ensure_handle returning False (secret missing)
    svc.secrets.request.return_value = (None, {"result": {"ok": False}})

    # Mock tool routing logic for secret.ensure
    res = await svc._route_tool("u1", {
        "tool_name": "secure.secret.ensure",
        "payload": {"handle": "missing_key"}
    })

    assert res["status"] == "secret_requested"

    # Verify Gate notification
    svc.tg_gate.request.assert_called_with(
        "gate.request_secret",
        {"principal_id": "u1", "handle": "missing_key"}
    )