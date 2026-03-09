from __future__ import annotations

import json

from shared.session_registry import SessionRegistry


def test_ensure_session_creates_index_and_session_file(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    registry = SessionRegistry()
    record = registry.ensure_session("private_main")

    assert record["session_key"] == "private_main"
    assert record["thread_id"] is None
    assert (tmp_path / "agent_repo" / "sessions" / "private_main.json").exists()
    index = json.loads((tmp_path / "agent_repo" / "sessions" / "sessions.json").read_text(encoding="utf-8"))
    assert "private_main" in index["sessions"]


def test_bind_thread_updates_session_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    registry = SessionRegistry()
    record = registry.bind_thread("group_1_topic_99", "thread-123")

    assert record["thread_id"] == "thread-123"
    assert record["status"] == "active"
    session_payload = json.loads((tmp_path / "agent_repo" / "sessions" / "group_1_topic_99.json").read_text(encoding="utf-8"))
    assert session_payload["thread_id"] == "thread-123"


def test_mark_restart_generation_invalidates_threads(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    registry = SessionRegistry()
    registry.bind_thread("private_main", "thread-a")
    index = registry.mark_restart_generation()

    assert index["restart_generation"] == 1
    session_payload = json.loads((tmp_path / "agent_repo" / "sessions" / "private_main.json").read_text(encoding="utf-8"))
    assert session_payload["thread_id"] is None
    assert session_payload["status"] == "stale:restart"
    assert session_payload["restart_generation"] == 1


def test_add_task_ref_updates_session(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    registry = SessionRegistry()
    record = registry.add_task_ref("private_main", "task-1")

    assert record["task_refs"] == ["task-1"]
