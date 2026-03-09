from __future__ import annotations

import json

import pytest

from shared.codex_session_manager import CodexSessionManager
from shared.session_registry import SessionRegistry


class FakeRuntime:
    def __init__(self):
        self.calls = []

    async def ensure_started(self):
        self.calls.append(("ensure_started",))
        return {"running": True}

    async def start_conversation(self, prompt: str, **kwargs):
        self.calls.append(("start", prompt, kwargs))
        return {"structuredContent": {"threadId": "thread-new", "content": "hydrated"}}

    async def continue_conversation(self, prompt: str, thread_id: str):
        self.calls.append(("reply", prompt, thread_id))
        return {"structuredContent": {"threadId": thread_id, "content": f"reply:{prompt}"}}

    async def health(self):
        self.calls.append(("health",))
        return {"running": True, "initialized": True}


@pytest.mark.asyncio
async def test_ensure_session_hydrates_when_no_thread(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    runtime = FakeRuntime()
    manager = CodexSessionManager(runtime=runtime, registry=SessionRegistry())

    record = await manager.ensure_session("private_main")

    assert record["thread_id"] == "thread-new"
    assert runtime.calls[0] == ("ensure_started",)
    assert runtime.calls[1][0] == "start"
    prompt = runtime.calls[1][1]
    assert "Reconstruct this session from the repository state and continue coherently." in prompt
    assert "- session_key: private_main" in prompt


@pytest.mark.asyncio
async def test_send_message_uses_existing_thread(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    registry = SessionRegistry()
    registry.bind_thread("private_main", "thread-existing")
    runtime = FakeRuntime()
    manager = CodexSessionManager(runtime=runtime, registry=registry)

    result = await manager.send_message("private_main", "hello")

    assert result["thread_id"] == "thread-new"
    assert runtime.calls[1][0] == "start"


@pytest.mark.asyncio
async def test_refresh_memory_bootstraps_agent_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    manager = CodexSessionManager(runtime=FakeRuntime(), registry=SessionRegistry())

    result = await manager.refresh_memory()

    assert result["root"].endswith("agent_repo")
    task_index = json.loads((tmp_path / "agent_repo" / "tasks" / "task_index.json").read_text(encoding="utf-8"))
    assert task_index["version"] == 1
    assert "memory/inbox.md" in result["snapshot_keys"]


@pytest.mark.asyncio
async def test_runtime_health_proxies_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    manager = CodexSessionManager(runtime=FakeRuntime(), registry=SessionRegistry())

    result = await manager.runtime_health()

    assert result["running"] is True


@pytest.mark.asyncio
async def test_create_task_links_task_to_session(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    manager = CodexSessionManager(runtime=FakeRuntime(), registry=SessionRegistry())

    task = await manager.create_task(session_key="private_main", title="Do thing")

    assert task["title"] == "Do thing"
    session_payload = json.loads((tmp_path / "agent_repo" / "sessions" / "private_main.json").read_text(encoding="utf-8"))
    assert task["id"] in session_payload["task_refs"]


@pytest.mark.asyncio
async def test_append_inbox_does_not_create_or_update_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    manager = CodexSessionManager(runtime=FakeRuntime(), registry=SessionRegistry())

    entry = await manager.append_inbox(
        session_key="private_main",
        text="remember this",
        channel="cli",
        principal_id="cli:u1",
        metadata={"kind": "message"},
    )

    assert entry["text"] == "remember this"
    assert not (tmp_path / "agent_repo" / "memory" / "summaries" / "private_main.md").exists()


@pytest.mark.asyncio
async def test_capture_message_task_creates_then_updates_recent_task(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    manager = CodexSessionManager(runtime=FakeRuntime(), registry=SessionRegistry())

    created = await manager.capture_message_task(
        session_key="private_main",
        text="Build a release checklist",
        channel="cli",
        principal_id="cli:u1",
    )
    updated = await manager.capture_message_task(
        session_key="private_main",
        text="Also include rollback steps",
        channel="cli",
        principal_id="cli:u1",
    )

    assert created["action"] == "created"
    assert updated["action"] == "updated"
    tasks = (await manager.list_tasks(session_key="private_main"))["tasks"]
    assert len(tasks) == 1
    assert "rollback steps" in tasks[0]["details"]


@pytest.mark.asyncio
async def test_append_inbox_does_not_rewrite_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    manager = CodexSessionManager(runtime=FakeRuntime(), registry=SessionRegistry())

    manager.registry.ensure_session("private_main")

    await manager.append_inbox(
        session_key="private_main",
        text="Track the scheduler cleanup work",
        channel="cli",
        principal_id="cli:u1",
    )

    summary_body = (tmp_path / "agent_repo" / "memory" / "summaries" / "private_main.md").read_text(encoding="utf-8")

    assert summary_body.strip() == "# Session Summary: private_main"
