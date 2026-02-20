import pytest
from unittest.mock import AsyncMock

from services.sheriff_cli_gate.service import SheriffCliGateService


@pytest.mark.asyncio
async def test_non_slash_rejected():
    svc = SheriffCliGateService()
    res = await svc.handle_message({"text": "hello"}, None, "r1")
    assert res["kind"] == "error"


@pytest.mark.asyncio
async def test_help_command():
    svc = SheriffCliGateService()
    res = await svc.handle_message({"text": "/help"}, None, "r1")
    assert res["kind"] == "sheriff"
    assert "/status" in res["message"]


@pytest.mark.asyncio
async def test_secret_command_routes_to_requests():
    svc = SheriffCliGateService()
    svc.requests = AsyncMock()
    svc.requests.request.return_value = (None, {"result": {"status": "approved"}})

    res = await svc.handle_message({"text": "/secret gh_token abc123"}, None, "r1")

    assert res["kind"] == "sheriff"
    assert "approved" in res["message"]
    svc.requests.request.assert_called_with("requests.resolve_secret", {"key": "gh_token", "value": "abc123"})


@pytest.mark.asyncio
async def test_allow_tool_command_routes_to_policy_resolution():
    svc = SheriffCliGateService()
    svc.requests = AsyncMock()
    svc.requests.request.return_value = (None, {"result": {"status": "approved"}})

    res = await svc.handle_message({"text": "/allow-tool python"}, None, "r1")

    assert res["kind"] == "sheriff"
    assert "approved" in res["message"]
    svc.requests.request.assert_called_with("requests.resolve_tool", {"key": "python", "action": "always_allow"})
