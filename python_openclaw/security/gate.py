from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Callable

from python_openclaw.security.permissions import PermissionDeniedException, PermissionStore


@dataclass
class ApprovalPrompt:
    approval_id: str
    principal_id: str
    resource_type: str
    resource_value: str
    metadata: dict


@dataclass
class PendingAction:
    approval_id: str
    principal_id: str
    action_type: str
    metadata: dict
    callback: Callable[[bool], None] | None = None


class ApprovalGate:
    def __init__(self, store: PermissionStore):
        self.store = store
        self.pending: dict[str, ApprovalPrompt] = {}
        self.pending_actions: dict[str, PendingAction] = {}

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

    def request_action(self, principal_id: str, action_type: str, metadata: dict, callback: Callable[[bool], None] | None = None) -> PendingAction:
        approval_id = secrets.token_urlsafe(12)
        action = PendingAction(
            approval_id=approval_id,
            principal_id=principal_id,
            action_type=action_type,
            metadata=metadata,
            callback=callback,
        )
        self.pending_actions[approval_id] = action
        return action

    def apply_callback(self, approval_id: str, action: str) -> ApprovalPrompt | PendingAction | None:
        prompt = self.pending.pop(approval_id, None)
        if prompt:
            if action == "deny":
                self.store.set_decision(prompt.principal_id, prompt.resource_type, prompt.resource_value, "DENY")
            elif action == "always_allow":
                self.store.set_decision(prompt.principal_id, prompt.resource_type, prompt.resource_value, "ALLOW")
            return prompt

        pending_action = self.pending_actions.pop(approval_id, None)
        if not pending_action:
            return None

        approved = action == "approve_this_request"
        if pending_action.callback:
            pending_action.callback(approved)
        return pending_action
