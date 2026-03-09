from __future__ import annotations

import sqlite3
from pathlib import Path


class PermissionsStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _init(self) -> None:
        with self._conn() as conn:
            conn.execute(
                "create table if not exists permissions (principal_id text, resource_type text, resource_value text, decision text, primary key(principal_id,resource_type,resource_value))"
            )

    def get_decision(self, principal_id: str, resource_type: str, resource_value: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "select decision from permissions where principal_id=? and resource_type=? and resource_value=?",
                (principal_id, resource_type, resource_value),
            ).fetchone()
        return row[0] if row else None

    def set_decision(self, principal_id: str, resource_type: str, resource_value: str, decision: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "insert or replace into permissions (principal_id,resource_type,resource_value,decision) values (?,?,?,?)",
                (principal_id, resource_type, resource_value, decision),
            )
