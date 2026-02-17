from shared.approvals import ApprovalGate

def test_approval_request_lifecycle():
    gate = ApprovalGate()

    # 1. Request
    req = gate.request_permission("user1", "domain", "example.com", {"op": "test"})
    approval_id = req["approval_id"]
    assert approval_id in gate.pending
    assert gate.pending[approval_id]["principal_id"] == "user1"

    # 2. Approve (One-Off)
    result = gate.apply_callback(approval_id, "approve_this_request")
    assert result["action"] == "approve_this_request"

    # FIXED: It remains in pending until consumed because it's a one-off
    assert approval_id in gate.pending
    assert approval_id in gate.one_off

    # 3. Consume
    assert gate.consume_one_off(approval_id) is True

    # FIXED: Now it is removed from pending
    assert approval_id not in gate.pending

    # Cannot consume twice
    assert gate.consume_one_off(approval_id) is False

def test_approval_deny():
    gate = ApprovalGate()
    req = gate.request_permission("user1", "tool", "exec")
    approval_id = req["approval_id"]

    gate.apply_callback(approval_id, "deny")

    assert approval_id not in gate.pending
    assert approval_id not in gate.one_off
    assert gate.consume_one_off(approval_id) is False

def test_unknown_approval_id():
    gate = ApprovalGate()
    assert gate.apply_callback("missing", "allow") is None
    assert gate.consume_one_off("missing") is False