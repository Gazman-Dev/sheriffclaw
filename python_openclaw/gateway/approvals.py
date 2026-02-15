from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class ApprovalRequest:
    approval_id: str
    principal_id: str
    tool_name: str
    payload: dict
    reason: str | None


@dataclass
class CapabilityToken:
    token: str
    approval_id: str
    expires_at: datetime
    used: bool = False


class ApprovalManager:
    def __init__(self, ttl_seconds: int = 120):
        self.ttl_seconds = ttl_seconds
        self.pending: dict[str, ApprovalRequest] = {}
        self.tokens: dict[str, CapabilityToken] = {}
        self.decisions: dict[str, bool] = {}

    def request(self, principal_id: str, tool_name: str, payload: dict, reason: str | None = None) -> ApprovalRequest:
        approval_id = secrets.token_urlsafe(16)
        req = ApprovalRequest(approval_id, principal_id, tool_name, payload, reason)
        self.pending[approval_id] = req
        return req

    def decide(self, approval_id: str, approved: bool) -> str | None:
        self.decisions[approval_id] = approved
        self.pending.pop(approval_id, None)
        if not approved:
            return None
        token = secrets.token_urlsafe(24)
        cap = CapabilityToken(
            token=token,
            approval_id=approval_id,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds),
        )
        self.tokens[token] = cap
        return token

    def verify_and_consume(self, token: str) -> bool:
        cap = self.tokens.get(token)
        if not cap or cap.used:
            return False
        if datetime.now(timezone.utc) >= cap.expires_at:
            return False
        cap.used = True
        return True
