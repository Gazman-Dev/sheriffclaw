import time

from python_openclaw.gateway.approvals import ApprovalManager


def test_approval_token_one_time_and_expiry():
    mgr = ApprovalManager(ttl_seconds=1)
    req = mgr.request("p1", "secure.web.request", {"host": "api.github.com"})
    token = mgr.decide(req.approval_id, True)
    assert token
    assert mgr.verify_and_consume(token) is True
    assert mgr.verify_and_consume(token) is False

    req2 = mgr.request("p1", "secure.web.request", {"host": "api.github.com"})
    token2 = mgr.decide(req2.approval_id, True)
    time.sleep(1.1)
    assert mgr.verify_and_consume(token2) is False


def test_deny_returns_none():
    mgr = ApprovalManager()
    req = mgr.request("p", "secure.web.request", {})
    assert mgr.decide(req.approval_id, False) is None
