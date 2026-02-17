import pytest
from unittest.mock import AsyncMock
from services.sheriff_gateway.service import SheriffGatewayService


@pytest.mark.asyncio
async def test_gateway_continues_after_tool_needs_approval():
    svc = SheriffGatewayService()
    svc.ai = AsyncMock()
    svc._route_tool = AsyncMock(return_value={"status": "needs_tool_approval", "tool": "git"})

    async def ai_stream():
        yield {"event": "tool.call", "payload": {"tool_name": "tools.exec", "payload": {}}}

    async def mock_ai_request(op, payload, stream_events=False):
        if op == "agent.session.open":
            return [], {"result": {"session_handle": "s1"}}
        if op == "agent.session.user_message":
            import asyncio
            fut = asyncio.get_running_loop().create_future()
            fut.set_result({"result": {"status": "done"}})
            return ai_stream(), fut
        return [], {"result": {}}

    svc.ai.request.side_effect = mock_ai_request
    res = await svc.handle_user_message({"channel": "cli", "principal_external_id": "u1", "text": "run unsafe"}, AsyncMock(), "r1")
    assert res["status"] == "done"


@pytest.mark.asyncio
async def test_gateway_secret_request_passthrough():
    svc = SheriffGatewayService()
    svc.secrets = AsyncMock()
    svc.secrets.request.return_value = (None, {"result": {"ok": False}})

    res = await svc._route_tool("u1", {"tool_name": "secure.secret.ensure", "payload": {"handle": "missing_key"}})
    assert res == {"status": "needs_secret", "handle": "missing_key"}
