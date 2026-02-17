from __future__ import annotations

from shared.approvals import ApprovalGate
from shared.paths import gw_root
from shared.permissions_store import PermissionsStore


class SheriffPolicyService:
    def __init__(self) -> None:
        self.store = PermissionsStore(gw_root() / "state" / "permissions.db")
        self.gate = ApprovalGate()

    async def get_decision(self, payload, emit_event, req_id):
        decision = self.store.get_decision(payload["principal_id"], payload["resource_type"], payload["resource_value"])
        return {"decision": decision}

    async def set_decision(self, payload, emit_event, req_id):
        self.store.set_decision(payload["principal_id"], payload["resource_type"], payload["resource_value"], payload["decision"])
        return {"status": "saved"}

    async def request_permission(self, payload, emit_event, req_id):
        return self.gate.request_permission(payload["principal_id"], payload["resource_type"], payload["resource_value"], payload.get("metadata"))

    async def apply_callback(self, payload, emit_event, req_id):
        item = self.gate.apply_callback(payload["approval_id"], payload["action"])
        if not item:
            return {"status": "not_found"}
        if payload["action"] == "always_allow":
            self.store.set_decision(item["principal_id"], item["resource_type"], item["resource_value"], "ALLOW")
        elif payload["action"] == "deny":
            self.store.set_decision(item["principal_id"], item["resource_type"], item["resource_value"], "DENY")
        return {"status": "recorded", "approval_id": payload["approval_id"]}

    async def pending_list(self, payload, emit_event, req_id):
        return {"pending": list(self.gate.pending.values())}

    async def consume_one_off(self, payload, emit_event, req_id):
        return {"approved": self.gate.consume_one_off(payload["approval_id"])}

    def ops(self):
        return {
            "policy.get_decision": self.get_decision,
            "policy.set_decision": self.set_decision,
            "policy.request_permission": self.request_permission,
            "policy.apply_callback": self.apply_callback,
            "policy.pending_list": self.pending_list,
            "policy.consume_one_off": self.consume_one_off,
        }
