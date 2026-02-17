from __future__ import annotations

import uuid


class ApprovalGate:
    def __init__(self):
        self.pending: dict[str, dict] = {}
        self.one_off: set[str] = set()

    def request_permission(self, principal_id: str, resource_type: str, resource_value: str, metadata: dict | None = None) -> dict:
        approval_id = str(uuid.uuid4())
        item = {
            "approval_id": approval_id,
            "principal_id": principal_id,
            "resource_type": resource_type,
            "resource_value": resource_value,
            "metadata": metadata or {},
        }
        self.pending[approval_id] = item
        return item

    def apply_callback(self, approval_id: str, action: str) -> dict | None:
        item = self.pending.get(approval_id)
        if not item:
            return None
        item["action"] = action
        if action == "approve_this_request":
            self.one_off.add(approval_id)
        else:
            self.pending.pop(approval_id, None)
        return item

    def consume_one_off(self, approval_id: str) -> bool:
        if approval_id in self.one_off:
            self.one_off.remove(approval_id)
            self.pending.pop(approval_id, None)
            return True
        return False
