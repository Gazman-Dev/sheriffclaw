from __future__ import annotations

from python_openclaw.security.gate import ApprovalGate
from python_openclaw.security.permissions import PermissionDeniedException, PermissionStore
from shared.paths import gw_root


class SheriffPolicyService:
    def __init__(self) -> None:
        self.store = PermissionStore(gw_root() / "permissions.db")
        self.gate = ApprovalGate(self.store)

    async def get_decision(self, payload, emit_event, req_id):
        d = self.store.get_decision(payload["principal_id"], payload["resource_type"], payload["resource_value"])
        return {"decision": None if not d else d.decision}

    async def set_decision(self, payload, emit_event, req_id):
        self.store.set_decision(payload["principal_id"], payload["resource_type"], payload["resource_value"], payload["decision"])
        return {"status": "saved"}

    async def request_permission(self, payload, emit_event, req_id):
        exc = PermissionDeniedException(payload["principal_id"], payload["resource_type"], payload["resource_value"], payload.get("metadata", {}))
        p = self.gate.request(exc)
        return {"approval_id": p.approval_id, "principal_id": p.principal_id, "resource_type": p.resource_type, "resource_value": p.resource_value}

    async def apply_callback(self, payload, emit_event, req_id):
        item = self.gate.apply_callback(payload["approval_id"], payload["action"])
        if not item:
            return {"status": "not_found"}
        return {"status": "recorded", "approval_id": item.approval_id}

    async def pending_list(self, payload, emit_event, req_id):
        return {
            "pending": [
                {
                    "approval_id": p.approval_id,
                    "principal_id": p.principal_id,
                    "resource_type": p.resource_type,
                    "resource_value": p.resource_value,
                }
                for p in self.gate.pending.values()
            ]
        }

    def ops(self):
        return {
            "policy.get_decision": self.get_decision,
            "policy.set_decision": self.set_decision,
            "policy.request_permission": self.request_permission,
            "policy.apply_callback": self.apply_callback,
            "policy.pending_list": self.pending_list,
        }
