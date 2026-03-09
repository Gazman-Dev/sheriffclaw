from __future__ import annotations

import json

from shared.task_store import TaskStore


def test_create_task_updates_index_views_and_history(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    store = TaskStore()
    task = store.create_task(title="Investigate topic", session_key="private_main", details="details")

    index = json.loads((tmp_path / "agent_repo" / "tasks" / "task_index.json").read_text(encoding="utf-8"))
    assert task["id"] in index["tasks"]
    assert "Investigate topic" in (tmp_path / "agent_repo" / "tasks" / "open_tasks.md").read_text(encoding="utf-8")
    history_files = list((tmp_path / "agent_repo" / "tasks" / "task_history").glob("*.md"))
    assert history_files


def test_update_task_moves_between_views(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    store = TaskStore()
    task = store.create_task(title="Blocked item", session_key="private_main")
    updated = store.update_task(task["id"], status="blocked")

    assert updated["status"] == "blocked"
    assert "Blocked item" in (tmp_path / "agent_repo" / "tasks" / "blocked_tasks.md").read_text(encoding="utf-8")
