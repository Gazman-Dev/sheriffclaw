import pytest
from unittest.mock import AsyncMock
from services.sheriff_tools.service import SheriffToolsService


@pytest.fixture
def tools_svc(tmp_path, monkeypatch):
    monkeypatch.setattr("services.sheriff_tools.service.gw_root", lambda: tmp_path)
    svc = SheriffToolsService()
    svc.policy = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_exec_tool_allowed(tools_svc):
    tools_svc.policy.request.return_value = (None, {"result": {"decision": "ALLOW"}})
    result = await tools_svc.exec_tool({"principal_id": "u1", "argv": ["python", "-c", "print('ok')"]}, None, "r1")
    assert result["status"] == "executed"


@pytest.mark.asyncio
async def test_exec_tool_denied_returns_needs_tool_approval(tools_svc):
    tools_svc.policy.request.return_value = (None, {"result": {"decision": "DENY"}})
    result = await tools_svc.exec_tool({"principal_id": "u1", "argv": ["rm", "-rf", "/"]}, None, "r1")
    assert result == {"status": "needs_tool_approval", "tool": "rm"}


@pytest.mark.asyncio
async def test_disclose_output_check(tools_svc):
    tools_svc.policy.request.return_value = (None, {"result": {"decision": "ALLOW"}})
    run_res = await tools_svc.exec_tool({"principal_id": "u1", "argv": ["python", "-c", "print('secret')"], "taint": True}, None, "r1")

    run_id = run_res["run_id"]
    tools_svc.policy.request.side_effect = [(None, {"result": {"approval_id": "app-2"}})]
    disc_res = await tools_svc.disclose_output({"principal_id": "u1", "run_id": run_id}, None, "r2")
    assert disc_res["status"] == "approval_requested"

    tools_svc.policy.request.side_effect = None
    tools_svc.policy.request.return_value = (None, {"result": {"approved": True}})
    disc_res_2 = await tools_svc.disclose_output({"principal_id": "u1", "run_id": run_id, "approval_id": "app-2"}, None, "r3")
    assert disc_res_2["status"] == "ok"
