from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from shared.paths import gw_root
from shared.proc_rpc import ProcClient


class SheriffRequestsService:
    def __init__(self) -> None:
        state_dir = gw_root() / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "requests.db"

        self.tg_gate = ProcClient("sheriff-tg-gate", spawn_fallback=False)
        self.policy = ProcClient("sheriff-policy", spawn_fallback=False)
        self.gateway = ProcClient("sheriff-gateway", spawn_fallback=False)
        # Back-compat shim for tests that still mock direct secrets RPC.
        self.secrets = None

        self._init_db()

    async def _secrets(self, op: str, payload: dict):
        if self.secrets is not None:
            _, old = await self.secrets.request(op, payload)
            return old.get("result", {})
        _, res = await self.gateway.request("gateway.secrets.call", {"op": op, "payload": payload})
        outer = res.get("result", {})
        if isinstance(outer, dict) and "result" in outer:
            if not outer.get("ok", True):
                return {}
            inner = outer.get("result", {})
            return inner if isinstance(inner, dict) else {}
        return outer if isinstance(outer, dict) else {}

    @staticmethod
    def _now_ms() -> int:
        import time

        return int(time.time() * 1000)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS catalog_entries (
                    entry_id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    one_liner TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    immutable INTEGER NOT NULL,
                    UNIQUE(type, key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS request_instances (
                    request_id TEXT PRIMARY KEY,
                    entry_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    resolved_at INTEGER,
                    resolution_json TEXT,
                    FOREIGN KEY(entry_id) REFERENCES catalog_entries(entry_id)
                )
                """
            )

    def _get_entry(self, entry_type: str, key: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT entry_id, type, key, status, one_liner, context_json, created_at, updated_at, immutable FROM catalog_entries WHERE type=? AND key=?",
                (entry_type, key),
            ).fetchone()
        if not row:
            return None
        return {
            "entry_id": row[0],
            "type": row[1],
            "key": row[2],
            "status": row[3],
            "one_liner": row[4],
            "context_json": row[5],
            "created_at": row[6],
            "updated_at": row[7],
            "immutable": bool(row[8]),
        }

    def _insert_request_instance(self, conn: sqlite3.Connection, entry_id: str) -> str:
        request_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO request_instances(request_id, entry_id, status, created_at) VALUES(?, ?, 'requested', ?)",
            (request_id, entry_id, self._now_ms()),
        )
        return request_id

    def _resolve_instance(self, conn: sqlite3.Connection, entry_id: str, resolution: dict[str, Any]) -> str:
        row = conn.execute(
            "SELECT request_id FROM request_instances WHERE entry_id=? AND status='requested' ORDER BY created_at DESC LIMIT 1",
            (entry_id,),
        ).fetchone()
        now = self._now_ms()
        if row:
            request_id = row[0]
            conn.execute(
                "UPDATE request_instances SET status='resolved', resolved_at=?, resolution_json=? WHERE request_id=?",
                (now, json.dumps(resolution, ensure_ascii=False), request_id),
            )
            return request_id
        request_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO request_instances(request_id, entry_id, status, created_at, resolved_at, resolution_json) VALUES(?, ?, 'resolved', ?, ?, ?)",
            (request_id, entry_id, now, now, json.dumps(resolution, ensure_ascii=False)),
        )
        return request_id

    async def create_or_update(self, payload, emit_event, req_id):
        entry_type = payload["type"]
        key = payload["key"]
        one_liner = payload["one_liner"]
        context_obj = payload.get("context") or {}
        context_json = json.dumps(context_obj, ensure_ascii=False, sort_keys=True)
        force_notify = payload.get("force_notify", False)

        should_notify = False
        with self._conn() as conn:
            row = conn.execute(
                "SELECT entry_id, status, immutable, created_at FROM catalog_entries WHERE type=? AND key=?",
                (entry_type, key),
            ).fetchone()
            now = self._now_ms()
            if row is None:
                entry_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO catalog_entries(entry_id, type, key, status, one_liner, context_json, created_at, updated_at, immutable) VALUES(?, ?, ?, 'requested', ?, ?, ?, ?, 0)",
                    (entry_id, entry_type, key, one_liner, context_json, now, now),
                )
                should_notify = True
                is_immutable = False
            else:
                entry_id = row[0]
                current_status = row[1]
                is_immutable = bool(row[2]) or current_status == "approved"
                if is_immutable:
                    should_notify = force_notify
                else:
                    should_notify = force_notify or (current_status != "requested")
                    conn.execute(
                        "UPDATE catalog_entries SET status='requested', one_liner=?, context_json=?, updated_at=? WHERE entry_id=?",
                        (one_liner, context_json, now, entry_id),
                    )
            request_id = self._insert_request_instance(conn, entry_id)

        entry = self._get_entry(entry_type, key)

        if should_notify:
            await self.tg_gate.request(
                "gate.notify_request",
                {
                    "event": "request",
                    "type": entry_type,
                    "key": key,
                    "one_liner": entry["one_liner"],
                    "status": "requested",
                    "request_id": request_id,
                    "context": context_obj,
                },
            )

        return {
            "status": "requested",
            "entry": {
                "type": entry["type"],
                "key": entry["key"],
                "status": entry["status"],
                "one_liner": entry["one_liner"],
                "updated_at": entry["updated_at"],
            },
            "request_id": request_id,
        }

    async def search(self, payload, emit_event, req_id):
        query = payload.get("query") or ""
        types = payload.get("types")
        k = int(payload.get("k", 8))
        q_tokens = [t for t in query.lower().split() if t]
        with self._conn() as conn:
            if types:
                placeholders = ",".join("?" for _ in types)
                rows = conn.execute(
                    f"SELECT type, key, status, one_liner, context_json, updated_at FROM catalog_entries WHERE type IN ({placeholders})",
                    tuple(types),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT type, key, status, one_liner, context_json, updated_at FROM catalog_entries"
                ).fetchall()

        def _score(row) -> float:
            hay = f"{row[0]} {row[1]} {row[3]} {row[4]}".lower()
            if not q_tokens:
                return 0.0
            hit = sum(1 for t in q_tokens if t in hay)
            return hit / max(len(q_tokens), 1)

        ranked = sorted(rows, key=lambda r: (_score(r), int(r[5])), reverse=True)
        matches = []
        for row in ranked[:k]:
            matches.append(
                {
                    "type": row[0],
                    "key": row[1],
                    "status": row[2],
                    "one_liner": row[3],
                    "score": _score(row),
                    "updated_at": row[5],
                }
            )
        return {"matches": matches}

    async def get(self, payload, emit_event, req_id):
        entry = self._get_entry(payload["type"], payload["key"])
        if not entry:
            return {"status": "not_found"}
        return entry

    async def resolve_secret(self, payload, emit_event, req_id):
        key = payload["key"]
        deny = payload.get("deny", False)

        if deny:
            status = "denied"
            immutable = 0
            with self._conn() as conn:
                row = conn.execute("SELECT entry_id FROM catalog_entries WHERE type='secret' AND key=?", (key,)).fetchone()
                now = self._now_ms()
                if row is None:
                    entry_id = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO catalog_entries(entry_id, type, key, status, one_liner, context_json, created_at, updated_at, immutable) VALUES(?, 'secret', ?, ?, ?, '{}', ?, ?, ?)",
                        (entry_id, key, status, f"Secret denied for {key}", now, now, immutable),
                    )
                else:
                    entry_id = row[0]
                    conn.execute("UPDATE catalog_entries SET status=?, immutable=?, updated_at=? WHERE entry_id=?",
                                 (status, immutable, now, entry_id))
                request_id = self._resolve_instance(conn, entry_id, {"action": "deny_secret"})

            await self.tg_gate.request(
                "gate.notify_request_resolved",
                {"event": "request_resolved", "type": "secret", "key": key, "status": "denied", "request_id": request_id, "context": {}},
            )
            await self.gateway.request("gateway.notify_request_resolved",
                                       {"type": "secret", "key": key, "status": "denied"})
            return {"status": "denied", "type": "secret", "key": key}

        unlocked = await self._secrets("secrets.is_unlocked", {})
        if not unlocked.get("unlocked"):
            return {"status": "master_password_required", "type": "secret", "key": key}

        await self._secrets("secrets.set_secret", {"handle": key, "value": payload["value"]})
        with self._conn() as conn:
            row = conn.execute("SELECT entry_id FROM catalog_entries WHERE type='secret' AND key=?", (key,)).fetchone()
            now = self._now_ms()
            if row is None:
                entry_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO catalog_entries(entry_id, type, key, status, one_liner, context_json, created_at, updated_at, immutable) VALUES(?, 'secret', ?, 'approved', ?, '{}', ?, ?, 1)",
                    (entry_id, key, f"Secret provided for {key}", now, now),
                )
            else:
                entry_id = row[0]
                conn.execute("UPDATE catalog_entries SET status='approved', immutable=1, updated_at=? WHERE entry_id=?",
                             (now, entry_id))
            request_id = self._resolve_instance(conn, entry_id, {"action": "provide_secret"})

        await self.tg_gate.request(
            "gate.notify_request_resolved",
            {"event": "request_resolved", "type": "secret", "key": key, "status": "approved", "request_id": request_id,
             "context": {}},
        )
        await self.gateway.request("gateway.notify_request_resolved",
                                   {"type": "secret", "key": key, "status": "approved"})
        return {"status": "approved", "type": "secret", "key": key}

    async def _resolve_policy_item(self, entry_type: str, key: str, action: str) -> dict[str, str]:
        if action == "always_allow":
            await self.policy.request(
                "policy.set_decision",
                {"principal_id": "default", "resource_type": entry_type, "resource_value": key, "decision": "ALLOW"},
            )
            status = "approved"
            immutable = 1
        elif action == "deny":
            await self.policy.request(
                "policy.set_decision",
                {"principal_id": "default", "resource_type": entry_type, "resource_value": key, "decision": "DENY"},
            )
            status = "denied"
            immutable = 0
        else:
            raise ValueError("unsupported action")

        with self._conn() as conn:
            row = conn.execute("SELECT entry_id FROM catalog_entries WHERE type=? AND key=?",
                               (entry_type, key)).fetchone()
            now = self._now_ms()
            if row is None:
                entry_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO catalog_entries(entry_id, type, key, status, one_liner, context_json, created_at, updated_at, immutable) VALUES(?, ?, ?, ?, ?, '{}', ?, ?, ?)",
                    (entry_id, entry_type, key, status, f"{entry_type} decision for {key}", now, now, immutable),
                )
            else:
                entry_id = row[0]
                conn.execute("UPDATE catalog_entries SET status=?, immutable=?, updated_at=? WHERE entry_id=?",
                             (status, immutable, now, entry_id))
            request_id = self._resolve_instance(conn, entry_id, {"action": action})

        await self.tg_gate.request(
            "gate.notify_request_resolved",
            {"event": "request_resolved", "type": entry_type, "key": key, "status": status, "request_id": request_id,
             "context": {}},
        )
        await self.gateway.request("gateway.notify_request_resolved",
                                   {"type": entry_type, "key": key, "status": status})
        return {"status": status, "type": entry_type, "key": key}

    async def resolve_domain(self, payload, emit_event, req_id):
        return await self._resolve_policy_item("domain", payload["key"], payload["action"])

    async def resolve_tool(self, payload, emit_event, req_id):
        return await self._resolve_policy_item("tool", payload["key"], payload["action"])

    async def resolve_disclose_output(self, payload, emit_event, req_id):
        return await self._resolve_policy_item("disclose_output", payload["key"], payload["action"])

    async def boot_check(self, payload, emit_event, req_id):
        unlocked = await self._secrets("secrets.is_unlocked", {})
        if unlocked.get("unlocked"):
            return {"status": "ok"}

        policy_path = gw_root() / "state" / "master_policy.json"
        allowed = False
        if policy_path.exists():
            data = json.loads(policy_path.read_text(encoding="utf-8"))
            allowed = bool(data.get("allow_telegram_master_password"))
        if allowed:
            await self.tg_gate.request("gate.notify_master_password_required", {"event": "master_password_required"})
            return {"status": "master_password_required"}
        return {"status": "ok"}

    async def submit_master_password(self, payload, emit_event, req_id):
        res = await self._secrets("secrets.unlock", {"master_password": payload["master_password"]})
        ok = bool(res.get("ok"))
        if ok:
            await self.tg_gate.request("gate.notify_master_password_accepted", {"event": "master_password_accepted"})
            await self.gateway.request(
                "gateway.notify_request_resolved",
                {"type": "master_password", "key": "master_password", "status": "approved"},
            )
        return {"ok": ok}

    def ops(self):
        return {
            "requests.create_or_update": self.create_or_update,
            "requests.search": self.search,
            "requests.get": self.get,
            "requests.resolve_secret": self.resolve_secret,
            "requests.resolve_domain": self.resolve_domain,
            "requests.resolve_tool": self.resolve_tool,
            "requests.resolve_disclose_output": self.resolve_disclose_output,
            "requests.boot_check": self.boot_check,
            "requests.submit_master_password": self.submit_master_password,
        }
