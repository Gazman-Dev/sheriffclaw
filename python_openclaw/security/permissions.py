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
    timestamp: str


class PermissionStore:
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
                    decision TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    PRIMARY KEY (principal_id, resource_type, resource_value)
                )
                """
            )

    def set_decision(self, principal_id: str, resource_type: str, resource_value: str, decision: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO permissions(principal_id, resource_type, resource_value, decision, timestamp)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(principal_id, resource_type, resource_value)
                DO UPDATE SET decision=excluded.decision, timestamp=excluded.timestamp
                """,
                (principal_id, resource_type, resource_value, decision, now),
            )

    def get_decision(self, principal_id: str, resource_type: str, resource_value: str) -> PermissionDecision | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT principal_id, resource_type, resource_value, decision, timestamp
                FROM permissions WHERE principal_id=? AND resource_type=? AND resource_value=?
                """,
                (principal_id, resource_type, resource_value),
            ).fetchone()
        if not row:
            return None
        return PermissionDecision(*row)


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
            if decision and decision.decision == "DENY":
                raise PermissionDeniedException(principal_id, resource_type, resource_value, metadata)
        raise PermissionDeniedException(principal_id, resource_type, resource_value, metadata)
