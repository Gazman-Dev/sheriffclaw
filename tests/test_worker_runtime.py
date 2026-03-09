from __future__ import annotations

import json

import pytest

from shared.worker.worker_runtime import WorkerRuntime


class FakeSessionManager:
    def __init__(self):
        self.calls = []

    async def ensure_session(self, session_key: str, *, hydrate: bool = True):
        self.calls.append(("ensure", session_key, hydrate))
        return {"session_key": session_key, "thread_id": None, "status": "new"}

    async def invalidate_session(self, session_key: str, *, reason: str = "manual"):
        self.calls.append(("invalidate", session_key, reason))
        return {"session_key": session_key, "thread_id": None, "status": f"stale:{reason}"}

    async def send_message(self, session_key: str, prompt: str):
        self.calls.append(("send", session_key, prompt))
        return {
            "session": {"session_key": session_key, "thread_id": "thread-1", "status": "active"},
            "thread_id": "thread-1",
            "result": {"structuredContent": {"threadId": "thread-1", "content": f"reply:{prompt}"}},
        }


@pytest.mark.asyncio
async def test_session_open_uses_private_main_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    manager = FakeSessionManager()
    runtime = WorkerRuntime(session_manager=manager)

    session_key = await runtime.session_open(None)

    assert session_key == "private_main"
    assert manager.calls == [("ensure", "private_main", False)]


@pytest.mark.asyncio
async def test_session_close_invalidates_session(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    manager = FakeSessionManager()
    runtime = WorkerRuntime(session_manager=manager)

    await runtime.session_close("group_1_topic_2")

    assert manager.calls == [("invalidate", "group_1_topic_2", "close")]


@pytest.mark.asyncio
async def test_user_message_emits_final_from_session_manager(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    manager = FakeSessionManager()
    runtime = WorkerRuntime(session_manager=manager)
    events = []

    async def emit(event, payload):
        events.append((event, payload))

    await runtime.user_message("private_main", "hello", None, emit)

    assert manager.calls == [("send", "private_main", "hello")]
    assert events == [("assistant.final", {"text": "reply:hello"})]


@pytest.mark.asyncio
async def test_user_message_emits_final_from_content_list(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    manager = FakeSessionManager()

    async def fake_send_message(session_key: str, prompt: str):
        manager.calls.append(("send", session_key, prompt))
        return {
            "session": {"session_key": session_key, "thread_id": "thread-1", "status": "active"},
            "thread_id": "thread-1",
            "result": {
                "structuredContent": {"threadId": "thread-1", "content": ""},
                "content": [{"type": "text", "text": "reply-from-content"}],
            },
        }

    manager.send_message = fake_send_message
    runtime = WorkerRuntime(session_manager=manager)
    events = []

    async def emit(event, payload):
        events.append((event, payload))

    await runtime.user_message("private_main", "hello", None, emit)

    assert manager.calls == [("send", "private_main", "hello")]
    assert events == [("assistant.final", {"text": "reply-from-content"})]


@pytest.mark.asyncio
async def test_tool_result_is_noop(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    runtime = WorkerRuntime(session_manager=FakeSessionManager())

    assert await runtime.tool_result("private_main", "requests.resolved", {"ok": True}) is None


@pytest.mark.asyncio
async def test_list_skills_reads_agent_repo_and_system_skills(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    user_skill = tmp_path / "agent_repo" / "skills" / "demo"
    user_skill.mkdir(parents=True, exist_ok=True)
    (user_skill / "manifest.json").write_text(
        json.dumps(
            {
                "skill_id": "demo",
                "description": "demo skill",
                "command": "python run.py",
                "tags": ["demo"],
            }
        ),
        encoding="utf-8",
    )

    runtime = WorkerRuntime(session_manager=FakeSessionManager())
    skills = await runtime.list_skills()

    assert any(skill["name"] == "demo" and skill["source"] == "user" for skill in skills)


@pytest.mark.asyncio
async def test_skill_run_executes_run_py(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    skill_root = tmp_path / "agent_repo" / "skills" / "echoer"
    skill_root.mkdir(parents=True, exist_ok=True)
    (skill_root / "manifest.json").write_text(
        json.dumps({"skill_id": "echoer", "description": "echo", "command": "python run.py"}),
        encoding="utf-8",
    )
    (skill_root / "run.py").write_text(
        "import json, sys\npayload = json.load(sys.stdin)\nprint(payload['value'])\n",
        encoding="utf-8",
    )

    runtime = WorkerRuntime(session_manager=FakeSessionManager())
    runtime.skills = runtime.skill_loader.load()

    result = await runtime.skill_run("echoer", {"value": "ok"}, lambda e, p: None)

    assert result["code"] == 0
    assert result["stdout"].strip() == "ok"
