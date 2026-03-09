from __future__ import annotations

from shared.memory_store import MemoryStore


def test_append_inbox_persists_jsonl_entry(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    store = MemoryStore()
    entry = store.append_inbox(
        session_key="private_main",
        text="hello world",
        channel="cli",
        principal_id="cli:u1",
        metadata={"foo": "bar"},
    )

    body = (tmp_path / "agent_repo" / "memory" / "inbox.md").read_text(encoding="utf-8")
    assert '"text": "hello world"' in body
    assert entry["session_key"] == "private_main"


def test_append_session_note_updates_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    store = MemoryStore()
    path = store.append_session_note("private_main", "noted")

    assert path.read_text(encoding="utf-8").startswith("# Session Summary: private_main")
    assert "- noted" in path.read_text(encoding="utf-8")


def test_reconcile_summary_and_global_memory(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    store = MemoryStore()
    store.append_inbox(
        session_key="private_main",
        text="Build the memory reconciler",
        channel="cli",
        principal_id="cli:u1",
    )
    store.append_decision(session_key="private_main", text="Use deterministic summary sections", source="test")

    session_result = store.reconcile_session_summary("private_main", task_lines=["- task-1 [open] Memory work"])
    global_result = store.reconcile_global_memory(
        task_lines=["- task-1 [open] Memory work"],
        session_keys=["private_main", "group_1_topic_2"],
    )

    summary_body = (tmp_path / "agent_repo" / "memory" / "summaries" / "private_main.md").read_text(encoding="utf-8")
    projects_body = (tmp_path / "agent_repo" / "memory" / "ongoing_projects.md").read_text(encoding="utf-8")
    patterns_body = (tmp_path / "agent_repo" / "memory" / "learned_patterns.md").read_text(encoding="utf-8")
    skills_body = (tmp_path / "agent_repo" / "memory" / "skill_candidates.md").read_text(encoding="utf-8")

    assert session_result["session_key"] == "private_main"
    assert global_result["session_count"] == 2
    assert "Build the memory reconciler" in summary_body
    assert "Active Task Snapshot" in projects_body
    assert "private_main had 1 recent captured messages" in patterns_body
    assert "task-manager skill" in skills_body
