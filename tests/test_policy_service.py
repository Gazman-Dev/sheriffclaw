import pytest
from services.sheriff_policy.service import SheriffPolicyService

@pytest.fixture
def policy_svc(tmp_path, monkeypatch):
    monkeypatch.setattr("services.sheriff_policy.service.gw_root", lambda: tmp_path)
    return SheriffPolicyService()

@pytest.mark.asyncio
async def test_policy_get_set_decision(policy_svc):
    # Default is None/Deny usually
    res = await policy_svc.get_decision({
        "principal_id": "u1",
        "resource_type": "domain",
        "resource_value": "example.com"
    }, None, "r1")
    assert res["decision"] is None

    # Set Allow
    await policy_svc.set_decision({
        "principal_id": "u1",
        "resource_type": "domain",
        "resource_value": "example.com",
        "decision": "ALLOW"
    }, None, "r2")

    res = await policy_svc.get_decision({
        "principal_id": "u1",
        "resource_type": "domain",
        "resource_value": "example.com"
    }, None, "r3")
    assert res["decision"] == "ALLOW"

@pytest.mark.asyncio
async def test_policy_approval_request(policy_svc):
    # Request permission
    req = await policy_svc.request_permission({
        "principal_id": "u1",
        "resource_type": "tool",
        "resource_value": "exec",
        "metadata": {}
    }, None, "r1")

    approval_id = req["approval_id"]
    assert approval_id

    # List pending
    pending = await policy_svc.pending_list({}, None, "r2")
    assert len(pending["pending"]) == 1
    assert pending["pending"][0]["approval_id"] == approval_id

    # Apply callback (approve)
    await policy_svc.apply_callback({
        "approval_id": approval_id,
        "action": "approve_this_request"
    }, None, "r3")

    # Check consumed
    consumed = await policy_svc.consume_one_off({"approval_id": approval_id}, None, "r4")
    assert consumed["approved"] is True