from pathlib import Path

import pytest

from python_openclaw.security.permissions import PermissionDeniedException, PermissionEnforcer, PermissionStore


def test_permission_store_persists(tmp_path: Path):
    store = PermissionStore(tmp_path / "perm.db")
    store.set_decision("u1", "domain", "api.github.com", "ALLOW")
    store2 = PermissionStore(tmp_path / "perm.db")
    decision = store2.get_decision("u1", "domain", "api.github.com")
    assert decision and decision.decision == "ALLOW"


def test_permission_enforcer_uses_allowlist_and_store(tmp_path: Path):
    store = PermissionStore(tmp_path / "perm.db")
    enforcer = PermissionEnforcer(config_allowlists={"domain": {"example.com"}}, store=store)
    enforcer.ensure_allowed("u", "domain", "example.com")

    store.set_decision("u", "domain", "api.github.com", "DENY")
    with pytest.raises(PermissionDeniedException):
        enforcer.ensure_allowed("u", "domain", "api.github.com")
