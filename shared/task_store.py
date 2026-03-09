from __future__ import annotations

import json
import time
import uuid
from typing import Any

from shared import agent_repo


TASK_STATUS_BUCKETS = {
    "open": "open_tasks.md",
    "in_progress": "open_tasks.md",
    "blocked": "blocked_tasks.md",
    "completed": "completed_tasks.md",
}


class TaskStore:
    def __init__(self) -> None:
        agent_repo.ensure_layout()
        self.index_path = agent_repo.path_for("tasks", "task_index.json")

    def create_task(
        self,
        *,
        title: str,
        session_key: str,
        details: str = "",
        owner: str = "codex",
        status: str = "open",
        refs: list[str] | None = None,
    ) -> dict[str, Any]:
        index = self._load_index()
        task_id = f"task-{uuid.uuid4().hex[:10]}"
        now = time.time()
        task = {
            "id": task_id,
            "title": title,
            "details": details,
            "status": status,
            "owner": owner,
            "session_key": session_key,
            "refs": list(refs or []),
            "created_at": now,
            "updated_at": now,
        }
        index["tasks"][task_id] = task
        self._write_index(index)
        self._render_views(index)
        self._append_history(f"CREATE {task_id} [{status}] {title}")
        return task

    def update_task(self, task_id: str, **changes: Any) -> dict[str, Any]:
        index = self._load_index()
        task = dict(index["tasks"][task_id])
        task.update({k: v for k, v in changes.items() if v is not None})
        task["updated_at"] = time.time()
        index["tasks"][task_id] = task
        self._write_index(index)
        self._render_views(index)
        self._append_history(f"UPDATE {task_id} [{task['status']}] {task['title']}")
        return task

    def append_note(self, task_id: str, note: str, *, ref: str | None = None) -> dict[str, Any]:
        index = self._load_index()
        task = dict(index["tasks"][task_id])
        details = str(task.get("details") or "").rstrip()
        if details:
            details += "\n\n"
        details += f"- {note.strip()}"
        task["details"] = details
        refs = list(task.get("refs", []))
        if ref and ref not in refs:
            refs.append(ref)
        task["refs"] = refs
        task["updated_at"] = time.time()
        index["tasks"][task_id] = task
        self._write_index(index)
        self._render_views(index)
        self._append_history(f"NOTE {task_id} {note.strip()}")
        return task

    def list_tasks(self, *, status: str | None = None, session_key: str | None = None) -> list[dict[str, Any]]:
        tasks = list(self._load_index()["tasks"].values())
        if status is not None:
            tasks = [task for task in tasks if task.get("status") == status]
        if session_key is not None:
            tasks = [task for task in tasks if task.get("session_key") == session_key]
        return sorted(tasks, key=lambda item: (item.get("status", ""), item.get("updated_at", 0), item.get("id", "")))

    def open_tasks_for_session(self, session_key: str) -> list[dict[str, Any]]:
        return [
            task
            for task in self.list_tasks(session_key=session_key)
            if task.get("status") in {"open", "in_progress", "blocked"}
        ]

    def summary_lines(self, *, session_key: str | None = None, limit: int = 12) -> list[str]:
        tasks = self.list_tasks(session_key=session_key) if session_key else list(self._load_index()["tasks"].values())
        tasks = sorted(tasks, key=lambda item: item.get("updated_at", 0), reverse=True)[:limit]
        return [f"- {task['id']} [{task['status']}] {task['title']}" for task in tasks]

    def _load_index(self) -> dict[str, Any]:
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _write_index(self, payload: dict[str, Any]) -> None:
        self.index_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    def _render_views(self, index: dict[str, Any]) -> None:
        buckets = {
            "open_tasks.md": ["# Open Tasks"],
            "blocked_tasks.md": ["# Blocked Tasks"],
            "completed_tasks.md": ["# Completed Tasks"],
        }
        for task in index["tasks"].values():
            filename = TASK_STATUS_BUCKETS.get(task["status"], "open_tasks.md")
            buckets[filename].append(f"- {task['id']} [{task['status']}] {task['title']} ({task['session_key']})")
        for filename, lines in buckets.items():
            agent_repo.path_for("tasks", filename).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _append_history(self, line: str) -> None:
        day = time.strftime("%Y-%m-%d")
        path = agent_repo.path_for("tasks", "task_history", f"{day}.md")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} {line}\n")
