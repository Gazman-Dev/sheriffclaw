from __future__ import annotations

import secrets
from dataclasses import dataclass

from python_openclaw.security.permissions import PermissionDeniedException, PermissionStore


@dataclass
class ApprovalPrompt:
    approval_id: str
    principal_id: str
    resource_type: str
    resource_value: str
    metadata: dict


class ApprovalGate:
    def __init__(self, store: PermissionStore):
        self.store = store
        self.pending: dict[str, ApprovalPrompt] = {}

    def request(self, exc: PermissionDeniedException) -> ApprovalPrompt:
        approval_id = secrets.token_urlsafe(12)
        prompt = ApprovalPrompt(
            approval_id=approval_id,
            principal_id=exc.principal_id,
            resource_type=exc.resource_type,
            resource_value=exc.resource_value,
            metadata=exc.metadata,
        )
        self.pending[approval_id] = prompt
        return prompt

    def apply_callback(self, approval_id: str, action: str) -> ApprovalPrompt | None:
        prompt = self.pending.pop(approval_id, None)
        if not prompt:
            return None
        if action == "deny":
            self.store.set_decision(prompt.principal_id, prompt.resource_type, prompt.resource_value, "DENY")
        elif action in {"always_allow", "allow_once"}:
            if action == "always_allow":
                self.store.set_decision(prompt.principal_id, prompt.resource_type, prompt.resource_value, "ALLOW")
        return prompt
