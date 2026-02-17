import pytest
from unittest.mock import AsyncMock, MagicMock
from services.sheriff_tools.service import SheriffToolsService

@pytest.fixture
def tools_svc(tmp_path, monkeypatch):
    monkeypatch.setattr("services.sheriff_tools.service.gw_root", lambda: tmp_path)
    svc = SheriffToolsService()
    svc.policy = AsyncMock() # Mock ProcClient
    return svc

@pytest.mark.asyncio
async def test_exec_tool_allowed(tools_svc):
    # Mock Policy ALLOW
    tools_svc.policy.request.return_value = (None, {"result": {"decision": "ALLOW"}})

    result = await tools_svc.exec_tool({
        "principal_id": "u1",
        "argv": ["python", "-c", "print('ok')"]
    }, None, "r1")

    assert result["status"] == "executed"
    assert "ok" in result["stdout"]

@pytest.mark.asyncio
async def test_exec_tool_denied_triggers_approval(tools_svc):
    # Mock Policy DENY -> Request Permission
    tools_svc.policy.request.side_effect = [
        (None, {"result": {"decision": "DENY"}}),  # get_decision
        (None, {"result": {"approval_id": "app-1"}}) # request_permission
    ]

    result = await tools_svc.exec_tool({
        "principal_id": "u1",
        "argv": ["rm", "-rf", "/"]
    }, None, "r1")

    assert result["status"] == "approval_requested"
    assert result["approval_id"] == "app-1"

@pytest.mark.asyncio
async def test_disclose_output_check(tools_svc):
    # 1. Run tainted tool
    tools_svc.policy.request.return_value = (None, {"result": {"decision": "ALLOW"}})
    run_res = await tools_svc.exec_tool({
        "principal_id": "u1",
        "argv": ["python", "-c", "print('secret')"],
        "taint": True
    }, None, "r1")

    run_id = run_res["run_id"]

    # 2. Try disclose (simulate policy requires approval first)
    # The service calls consume_one_off first. 
    # If not approved, it calls request_permission.
    tools_svc.policy.request.side_effect = [
        (None, {"result": {"approval_id": "app-2"}}) # request_permission for disclose
    ]

    disc_res = await tools_svc.disclose_output({
        "principal_id": "u1",
        "run_id": run_id
    }, None, "r2")

    assert disc_res["status"] == "approval_requested"

    # 3. Simulate approved
    tools_svc.policy.request.side_effect = None
    tools_svc.policy.request.return_value = (None, {"result": {"approved": True}}) # consume_one_off

    disc_res_2 = await tools_svc.disclose_output({
        "principal_id": "u1",
        "run_id": run_id,
        "approval_id": "app-2"
    }, None, "r3")

    assert disc_res_2["status"] == "ok"
    assert "secret" in disc_res_2["stdout"]