from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class PermissionDeniedException(PermissionError):
    def __init__(self, principal_id: str, resource_type: str, resource_value: str, metadata: dict | None = None):
        super().__init__(f"permission denied: {resource_type}={resource_value}")
        self.principal_id = principal_id
        self.resource_type = resource_type
        self.resource_value = resource_value
        self.metadata = metadata or {}


@dataclass
class PermissionDecision:
    principal_id: str
    resource_type: str
    resource_value: str
    decision: str
    created_at: str


class PermissionStore:
    """Simple SQLite allow/deny store for gate decisions."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS permissions (
                    principal_id TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_value TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('ALLOW', 'DENY')),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (principal_id, resource_type, resource_value)
                )
                """
            )

    def set_decision(self, principal_id: str, resource_type: str, resource_value: str, decision: str) -> None:
        normalized = decision.upper()
        if normalized not in {"ALLOW", "DENY"}:
            raise ValueError("decision must be ALLOW or DENY")
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO permissions(principal_id, resource_type, resource_value, decision, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(principal_id, resource_type, resource_value)
                DO UPDATE SET decision=excluded.decision, created_at=excluded.created_at
                """,
                (principal_id, resource_type, resource_value, normalized, now),
            )

    def get_decision(self, principal_id: str, resource_type: str, resource_value: str) -> PermissionDecision | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT principal_id, resource_type, resource_value, decision, created_at
                FROM permissions WHERE principal_id=? AND resource_type=? AND resource_value=?
                """,
                (principal_id, resource_type, resource_value),
            ).fetchone()
        if not row:
            return None
        return PermissionDecision(*row)

    def is_allowed(self, principal_id: str, resource_type: str, resource_value: str) -> bool:
        decision = self.get_decision(principal_id, resource_type, resource_value)
        return bool(decision and decision.decision == "ALLOW")


class PermissionEnforcer:
    def __init__(self, *, config_allowlists: dict[str, set[str]] | None = None, store: PermissionStore | None = None):
        self.config_allowlists = config_allowlists or {}
        self.store = store

    def ensure_allowed(self, principal_id: str, resource_type: str, resource_value: str, metadata: dict | None = None) -> None:
        allowlist = self.config_allowlists.get(resource_type, set())
        if resource_value in allowlist:
            return
        if self.store:
            decision = self.store.get_decision(principal_id, resource_type, resource_value)
            if decision and decision.decision == "ALLOW":
                return
        raise PermissionDeniedException(principal_id, resource_type, resource_value, metadata)
