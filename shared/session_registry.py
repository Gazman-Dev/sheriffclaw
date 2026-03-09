from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from shared.agent_repo import ensure_layout, ensure_session_artifacts, path_for, session_file, summary_file


class SessionRegistry:
    def __init__(self) -> None:
        ensure_layout()
        self.index_path = path_for("sessions", "sessions.json")

    def load_index(self) -> dict[str, Any]:
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def ensure_session(self, session_key: str) -> dict[str, Any]:
        ensure_session_artifacts(session_key)
        index = self.load_index()
        sessions = index.setdefault("sessions", {})
        existing = sessions.get(session_key, {})
        now = time.time()
        record = {
            "session_key": session_key,
            "thread_id": existing.get("thread_id"),
            "status": existing.get("status", "new"),
            "last_used_at": existing.get("last_used_at", now),
            "summary_path": str(summary_file(session_key)),
            "session_path": str(session_file(session_key)),
            "task_refs": list(existing.get("task_refs", [])),
            "restart_generation": int(existing.get("restart_generation", index.get("restart_generation", 0))),
        }
        sessions[session_key] = record
        self._write_index(index)
        self._write_session_file(record)
        return record

    def mark_used(self, session_key: str) -> dict[str, Any]:
        record = self.ensure_session(session_key)
        record["last_used_at"] = time.time()
        self._update_session(record)
        return record

    def bind_thread(self, session_key: str, thread_id: str) -> dict[str, Any]:
        record = self.ensure_session(session_key)
        record["thread_id"] = thread_id
        record["status"] = "active"
        record["last_used_at"] = time.time()
        self._update_session(record)
        return record

    def invalidate_session(self, session_key: str, *, reason: str = "restart") -> dict[str, Any]:
        record = self.ensure_session(session_key)
        record["thread_id"] = None
        record["status"] = f"stale:{reason}"
        record["last_used_at"] = time.time()
        self._update_session(record)
        return record

    def add_task_ref(self, session_key: str, task_id: str) -> dict[str, Any]:
        record = self.ensure_session(session_key)
        refs = list(record.get("task_refs", []))
        if task_id not in refs:
            refs.append(task_id)
        record["task_refs"] = refs
        record["last_used_at"] = time.time()
        self._update_session(record)
        return record

    def mark_restart_generation(self) -> dict[str, Any]:
        index = self.load_index()
        next_generation = int(index.get("restart_generation", 0)) + 1
        index["restart_generation"] = next_generation
        sessions = index.setdefault("sessions", {})
        for session_key, record in sessions.items():
            updated = {
                **record,
                "thread_id": None,
                "status": "stale:restart",
                "restart_generation": next_generation,
                "last_used_at": time.time(),
            }
            sessions[session_key] = updated
            self._write_session_file(updated)
        self._write_index(index)
        return index

    def _update_session(self, record: dict[str, Any]) -> None:
        index = self.load_index()
        index.setdefault("sessions", {})[record["session_key"]] = record
        self._write_index(index)
        self._write_session_file(record)

    def _write_index(self, payload: dict[str, Any]) -> None:
        self.index_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    def _write_session_file(self, payload: dict[str, Any]) -> None:
        path = Path(payload["session_path"])
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
