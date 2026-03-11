import sys
from unittest.mock import AsyncMock

import pytest

from services.sheriff_tools.service import SheriffToolsService


@pytest.fixture
def tools_svc(tmp_path, monkeypatch):
    monkeypatch.setattr("services.sheriff_tools.service.gw_root", lambda: tmp_path)
    svc = SheriffToolsService()
    svc.policy = AsyncMock()
    svc.requests = AsyncMock()
    svc.secrets = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_exec_tool_allowed(tools_svc):
    tools_svc.policy.request.return_value = (None, {"result": {"decision": "ALLOW"}})
    tools_svc.secrets.request.side_effect = [
        (None, {"result": {"unlocked": True}}),
    ]
    result = await tools_svc.exec_tool({"principal_id": "u1", "argv": [sys.executable, "-c", "print('ok')"]}, None,
                                       "r1")
    assert result["status"] == "executed"


@pytest.mark.asyncio
async def test_exec_tool_denied_returns_needs_tool_approval(tools_svc):
    tools_svc.policy.request.return_value = (None, {"result": {"decision": "DENY"}})
    result = await tools_svc.exec_tool({"principal_id": "u1", "argv": ["rm", "-rf", "/"]}, None, "r1")
    assert result == {"status": "needs_tool_approval", "tool": "rm"}
    tools_svc.requests.request.assert_awaited()


@pytest.mark.asyncio
async def test_exec_tool_with_missing_secret_creates_request(tools_svc):
    tools_svc.policy.request.return_value = (None, {"result": {"decision": "ALLOW"}})
    tools_svc.secrets.request.side_effect = [
        (None, {"result": {"unlocked": True}}),
        (None, {"result": {"value": None}}),
    ]
    result = await tools_svc.exec_tool(
        {"principal_id": "u1", "argv": ["git", "clone", "x"], "env_handles": ["GIT_TOKEN"]},
        None,
        "r1",
    )
    assert result == {"status": "needs_secret", "missing_handles": ["GIT_TOKEN"]}
    tools_svc.requests.request.assert_any_await(
        "requests.create_or_update",
        {
            "type": "secret",
            "key": "GIT_TOKEN",
            "one_liner": "Need GIT_TOKEN to run git clone x",
            "context": {"title": "GIT_TOKEN", "tool": "git", "argv": ["git", "clone", "x"]},
        },
    )


@pytest.mark.asyncio
async def test_exec_tool_with_secret_env_uses_value(tools_svc):
    tools_svc.policy.request.return_value = (None, {"result": {"decision": "ALLOW"}})
    tools_svc.secrets.request.side_effect = [
        (None, {"result": {"unlocked": True}}),
        (None, {"result": {"value": "top-secret"}}),
    ]
    result = await tools_svc.exec_tool(
        {
            "principal_id": "u1",
            "argv": [sys.executable, "-c", "import os; print(os.environ['GIT_TOKEN'])"],
            "env_handles": ["GIT_TOKEN"],
        },
        None,
        "r1",
    )
    assert result["status"] == "executed"
    assert "top-secret" in result["stdout"]


@pytest.mark.asyncio
async def test_disclose_output_check_unified_flow(tools_svc):
    # Setup allowed execution
    tools_svc.policy.request.return_value = (None, {"result": {"decision": "ALLOW"}})
    run_res = await tools_svc.exec_tool(
        {"principal_id": "u1", "argv": [sys.executable, "-c", "print('secret')"], "taint": True}, None, "r1")
    run_id = run_res["run_id"]

    # Test denied disclosure (default)
    tools_svc.policy.request.return_value = (None, {"result": {"decision": "DENY"}})
    disc_res = await tools_svc.disclose_output({"principal_id": "u1", "run_id": run_id}, None, "r2")

    # Should now return 'needs_disclose_approval' instead of 'approval_requested'
    assert disc_res["status"] == "needs_disclose_approval"
    assert disc_res["run_id"] == run_id

    # Test allowed disclosure (simulated after requests.resolve_disclose_output sets policy)
    tools_svc.policy.request.return_value = (None, {"result": {"decision": "ALLOW"}})
    disc_res_2 = await tools_svc.disclose_output({"principal_id": "u1", "run_id": run_id}, None, "r3")
    assert disc_res_2["status"] == "ok"
