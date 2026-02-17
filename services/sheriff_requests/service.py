from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from shared.paths import gw_root
from shared.proc_rpc import ProcClient


class SheriffRequestsService:
    def __init__(self) -> None:
        state_dir = gw_root() / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "requests.db"
        self.vector_dir = state_dir / "requests_vectors"
        self.vector_dir.mkdir(parents=True, exist_ok=True)

        self.tg_gate = ProcClient("sheriff-tg-gate")
        self.secrets = ProcClient("sheriff-secrets")
        self.policy = ProcClient("sheriff-policy")
        self.gateway = ProcClient("sheriff-gateway")

        self._init_db()
        self.chroma = chromadb.PersistentClient(path=str(self.vector_dir))
        self.collection = self.chroma.get_or_create_collection(
            name="requests_catalog",
            embedding_function=self._embedding_function(),
        )

    @staticmethod
    def _embedding_function() -> SentenceTransformerEmbeddingFunction:
        return SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

    @staticmethod
    def _doc_id(entry_type: str, key: str) -> str:
        return f"{entry_type}:{key}"

    @staticmethod
    def _embedding_text(entry: dict[str, Any]) -> str:
        return f"{entry['type']}\n{entry['key']}\n{entry['one_liner']}\n{entry['context_json']}"

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

    def _upsert_chroma(self, entry: dict[str, Any]) -> None:
        doc_id = self._doc_id(entry["type"], entry["key"])
        self.collection.upsert(
            ids=[doc_id],
            documents=[self._embedding_text(entry)],
            metadatas=[
                {
                    "type": entry["type"],
                    "key": entry["key"],
                    "status": entry["status"],
                    "updated_at": int(entry["updated_at"]),
                }
            ],
        )

    def _upsert_existing_entry(self, entry_type: str, key: str) -> None:
        entry = self._get_entry(entry_type, key)
        if entry is not None:
            self._upsert_chroma(entry)

    async def create_or_update(self, payload, emit_event, req_id):
        entry_type = payload["type"]
        key = payload["key"]
        one_liner = payload["one_liner"]
        context_obj = payload.get("context") or {}
        context_json = json.dumps(context_obj, ensure_ascii=False, sort_keys=True)
        force_notify = payload.get("force_notify", False)

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
                should_update_content = True
                is_immutable = False
            else:
                entry_id = row[0]
                is_immutable = bool(row[2]) or row[1] == "approved"
                if is_immutable:
                    should_update_content = False
                else:
                    conn.execute(
                        "UPDATE catalog_entries SET status='requested', one_liner=?, context_json=?, updated_at=? WHERE entry_id=?",
                        (one_liner, context_json, now, entry_id),
                    )
                    should_update_content = True
            request_id = self._insert_request_instance(conn, entry_id)

        # Resilient upsert: Always ensure the entry is in Chroma, even if immutable.
        self._upsert_existing_entry(entry_type, key)

        entry = self._get_entry(entry_type, key)

        # Notify only if not immutable (fresh request) or forced
        if not is_immutable or force_notify:
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

        where = None
        if types:
            where = {"type": {"$in": list(types)}}

        result = self.collection.query(query_texts=[query], n_results=k, where=where)
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]

        matches = []
        for doc_id, distance in zip(ids, distances, strict=False):
            entry_type, key = doc_id.split(":", 1)
            entry = self._get_entry(entry_type, key)
            if entry is None:
                continue
            matches.append(
                {
                    "type": entry["type"],
                    "key": entry["key"],
                    "status": entry["status"],
                    "one_liner": entry["one_liner"],
                    "score": distance,
                    "updated_at": entry["updated_at"],
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
        _, unlocked = await self.secrets.request("secrets.is_unlocked", {})
        if not unlocked["result"].get("unlocked"):
            return {"status": "master_password_required", "type": "secret", "key": key}

        await self.secrets.request("secrets.set_secret", {"handle": key, "value": payload["value"]})
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
                conn.execute("UPDATE catalog_entries SET status='approved', immutable=1, updated_at=? WHERE entry_id=?", (now, entry_id))
            request_id = self._resolve_instance(conn, entry_id, {"action": "provide_secret"})

        self._upsert_existing_entry("secret", key)
        await self.tg_gate.request(
            "gate.notify_request_resolved",
            {"event": "request_resolved", "type": "secret", "key": key, "status": "approved", "request_id": request_id, "context": {}},
        )
        await self.gateway.request("gateway.notify_request_resolved", {"type": "secret", "key": key, "status": "approved"})
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
            row = conn.execute("SELECT entry_id FROM catalog_entries WHERE type=? AND key=?", (entry_type, key)).fetchone()
            now = self._now_ms()
            if row is None:
                entry_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO catalog_entries(entry_id, type, key, status, one_liner, context_json, created_at, updated_at, immutable) VALUES(?, ?, ?, ?, ?, '{}', ?, ?, ?)",
                    (entry_id, entry_type, key, status, f"{entry_type} decision for {key}", now, now, immutable),
                )
            else:
                entry_id = row[0]
                conn.execute("UPDATE catalog_entries SET status=?, immutable=?, updated_at=? WHERE entry_id=?", (status, immutable, now, entry_id))
            request_id = self._resolve_instance(conn, entry_id, {"action": action})

        self._upsert_existing_entry(entry_type, key)
        await self.tg_gate.request(
            "gate.notify_request_resolved",
            {"event": "request_resolved", "type": entry_type, "key": key, "status": status, "request_id": request_id, "context": {}},
        )
        await self.gateway.request("gateway.notify_request_resolved", {"type": entry_type, "key": key, "status": status})
        return {"status": status, "type": entry_type, "key": key}

    async def resolve_domain(self, payload, emit_event, req_id):
        return await self._resolve_policy_item("domain", payload["key"], payload["action"])

    async def resolve_tool(self, payload, emit_event, req_id):
        return await self._resolve_policy_item("tool", payload["key"], payload["action"])

    async def resolve_disclose_output(self, payload, emit_event, req_id):
        return await self._resolve_policy_item("disclose_output", payload["key"], payload["action"])

    async def boot_check(self, payload, emit_event, req_id):
        _, unlocked = await self.secrets.request("secrets.is_unlocked", {})
        if unlocked["result"].get("unlocked"):
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
        _, res = await self.secrets.request("secrets.unlock", {"master_password": payload["master_password"]})
        ok = bool(res["result"].get("ok"))
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