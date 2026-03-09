from __future__ import annotations

import asyncio

import pytest

from services.ai_worker.service import AIWorkerService


class FakeRuntime:
    async def session_open(self, session_id):
        return session_id or "primary"

    async def session_close(self, session_handle):
        return None

    async def user_message(self, session_handle, text, model_ref, emit_event, **kwargs):
        await emit_event("assistant.final", {"text": text})

    async def tool_result(self, session_handle, tool_name, result):
        return None

    async def list_skills(self):
        return []

    async def skill_run(self, name, payload, emit_event):
        return {"stdout": "", "stderr": "", "code": 0}


class FakeSessionManager:
    def __init__(self):
        self.calls = []

    async def ensure_session(self, session_key: str, *, hydrate: bool = True):
        self.calls.append(("ensure", session_key, hydrate))
        return {"session_key": session_key, "thread_id": "thread-1", "status": "active"}

    async def send_message(self, session_key: str, prompt: str, *, model: str | None = None):
        self.calls.append(("send", session_key, prompt, model))
        return {
            "session": {"session_key": session_key, "thread_id": "thread-1", "status": "active"},
            "thread_id": "thread-1",
            "result": {"structuredContent": {"threadId": "thread-1", "content": f"reply:{prompt}"}},
        }

    async def invalidate_session(self, session_key: str, *, reason: str = "manual"):
        self.calls.append(("invalidate", session_key, reason))
        return {"session_key": session_key, "thread_id": None, "status": f"stale:{reason}"}

    async def hydrate_session(self, session_key: str, *, reason: str = "hydrate"):
        self.calls.append(("hydrate", session_key, reason))
        return {"session_key": session_key, "thread_id": "thread-2", "status": "active"}

    async def refresh_memory(self):
        self.calls.append(("memory",))
        return {"root": "repo", "memory_files": ["a.md"]}

    async def runtime_health(self):
        self.calls.append(("health",))
        return {"running": True, "initialized": True}

    async def create_task(self, *, session_key: str, title: str, details: str = "", owner: str = "codex", status: str = "open", refs=None):
        self.calls.append(("task_create", session_key, title, details, owner, status, list(refs or [])))
        return {"id": "task-1", "session_key": session_key, "title": title, "status": status}

    async def list_tasks(self, *, session_key: str | None = None, status: str | None = None):
        self.calls.append(("task_list", session_key, status))
        return {"tasks": [{"id": "task-1"}]}

    async def append_inbox(self, *, session_key: str, text: str, channel: str, principal_id: str, metadata=None):
        self.calls.append(("inbox_append", session_key, text, channel, principal_id, metadata or {}))
        return {"session_key": session_key, "text": text}

    async def capture_message_task(self, *, session_key: str, text: str, channel: str, principal_id: str):
        self.calls.append(("task_capture", session_key, text, channel, principal_id))
        return {"action": "created", "task": {"id": "task-2"}}


@pytest.mark.asyncio
async def test_codex_session_ensure_uses_session_manager():
    manager = FakeSessionManager()
    svc = AIWorkerService(runtime=FakeRuntime(), session_manager=manager)

    result = await svc.codex_session_ensure({"session_key": "private_main"}, lambda e, p: None, "req-1")

    assert result["session"]["session_key"] == "private_main"
    assert manager.calls == [("ensure", "private_main", True)]


@pytest.mark.asyncio
async def test_codex_session_send_emits_assistant_final():
    manager = FakeSessionManager()
    svc = AIWorkerService(runtime=FakeRuntime(), session_manager=manager)
    events = []

    async def emit(event, payload):
        events.append((event, payload))

    result = await svc.codex_session_send({"session_key": "private_main", "prompt": "hello"}, emit, "req-2")

    assert result["thread_id"] == "thread-1"
    assert ("assistant.final", {"text": "reply:hello"}) in events
    assert manager.calls == [("send", "private_main", "hello", None)]


@pytest.mark.asyncio
async def test_codex_session_send_emits_assistant_final_from_content_list():
    manager = FakeSessionManager()
    manager.send_message = lambda session_key, prompt: None

    async def fake_send_message(session_key: str, prompt: str, *, model: str | None = None):
        manager.calls.append(("send", session_key, prompt, model))
        return {
            "session": {"session_key": session_key, "thread_id": "thread-1", "status": "active"},
            "thread_id": "thread-1",
            "result": {
                "structuredContent": {"threadId": "thread-1", "content": ""},
                "content": [{"type": "text", "text": "reply-from-content"}],
            },
        }

    manager.send_message = fake_send_message
    svc = AIWorkerService(runtime=FakeRuntime(), session_manager=manager)
    events = []

    async def emit(event, payload):
        events.append((event, payload))

    await svc.codex_session_send({"session_key": "private_main", "prompt": "hello"}, emit, "req-2b")

    assert ("assistant.final", {"text": "reply-from-content"}) in events
    assert manager.calls == [("send", "private_main", "hello", None)]


@pytest.mark.asyncio
async def test_codex_session_send_surfaces_tool_error():
    manager = FakeSessionManager()

    async def fake_send_message(session_key: str, prompt: str, *, model: str | None = None):
        manager.calls.append(("send", session_key, prompt, model))
        return {
            "session": {"session_key": session_key, "thread_id": "thread-1", "status": "active"},
            "thread_id": "thread-1",
            "result": {
                "content": [{"type": "text", "text": "unexpected status 401 Unauthorized"}],
                "structuredContent": {"threadId": "thread-1", "content": "unexpected status 401 Unauthorized"},
                "isError": True,
            },
        }

    manager.send_message = fake_send_message
    svc = AIWorkerService(runtime=FakeRuntime(), session_manager=manager)

    result = await svc.codex_session_send(
        {"session_key": "private_main", "prompt": "hello", "model_ref": "gpt-5-codex"},
        lambda e, p: None,
        "req-2c",
    )

    assert result["ok"] is False
    assert "401 Unauthorized" in result["error"]


@pytest.mark.asyncio
async def test_codex_session_invalidate_uses_reason():
    manager = FakeSessionManager()
    svc = AIWorkerService(runtime=FakeRuntime(), session_manager=manager)

    result = await svc.codex_session_invalidate(
        {"session_key": "group_1_topic_2", "reason": "restart"},
        lambda e, p: None,
        "req-3",
    )

    assert result["session"]["status"] == "stale:restart"
    assert manager.calls == [("invalidate", "group_1_topic_2", "restart")]


@pytest.mark.asyncio
async def test_codex_session_hydrate_and_memory_refresh():
    manager = FakeSessionManager()
    svc = AIWorkerService(runtime=FakeRuntime(), session_manager=manager)

    hydrated = await svc.codex_session_hydrate({"session_key": "private_main"}, lambda e, p: None, "req-4")
    refreshed = await svc.codex_memory_refresh({}, lambda e, p: None, "req-5")

    assert hydrated["session"]["thread_id"] == "thread-2"
    assert refreshed["memory_files"] == ["a.md"]
    assert manager.calls == [("hydrate", "private_main", "hydrate"), ("memory",)]


@pytest.mark.asyncio
async def test_codex_runtime_health():
    manager = FakeSessionManager()
    svc = AIWorkerService(runtime=FakeRuntime(), session_manager=manager)

    result = await svc.codex_runtime_health({}, lambda e, p: None, "req-6")

    assert result["running"] is True
    assert manager.calls == [("health",)]


def test_ai_worker_exports_only_mcp_or_skill_ops():
    svc = AIWorkerService(runtime=FakeRuntime(), session_manager=FakeSessionManager())
    ops = svc.ops()

    assert "codex.session.ensure" in ops
    assert "codex.session.send" in ops
    assert "skills.list" in ops
    assert "agent.session.open" not in ops
    assert "agent.session.user_message" not in ops


@pytest.mark.asyncio
async def test_codex_task_ops_and_inbox_append():
    manager = FakeSessionManager()
    svc = AIWorkerService(runtime=FakeRuntime(), session_manager=manager)

    created = await svc.codex_task_create({"session_key": "private_main", "title": "T1"}, lambda e, p: None, "req-7")
    listed = await svc.codex_task_list({"session_key": "private_main"}, lambda e, p: None, "req-8")
    inbox = await svc.codex_memory_inbox_append(
        {"session_key": "private_main", "text": "hello", "channel": "cli", "principal_id": "cli:u1"},
        lambda e, p: None,
        "req-9",
    )

    assert created["task"]["id"] == "task-1"
    assert listed["tasks"] == [{"id": "task-1"}]
    assert inbox["entry"]["text"] == "hello"


@pytest.mark.asyncio
async def test_codex_task_capture_from_message():
    manager = FakeSessionManager()
    svc = AIWorkerService(runtime=FakeRuntime(), session_manager=manager)

    result = await svc.codex_task_capture_from_message(
        {"session_key": "private_main", "text": "build me a plan", "channel": "cli", "principal_id": "cli:u1"},
        lambda e, p: None,
        "req-10",
    )

    assert result["action"] == "created"


def test_service_constructed_outside_loop_can_run_inside_event_loop():
    manager = FakeSessionManager()
    svc = AIWorkerService(runtime=FakeRuntime(), session_manager=manager)

    result = asyncio.run(svc.codex_session_ensure({"session_key": "private_main"}, lambda e, p: None, "req-loop"))

    assert result["session"]["session_key"] == "private_main"
