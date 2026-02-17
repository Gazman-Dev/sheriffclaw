import pytest
from unittest.mock import MagicMock
from shared.worker.worker_runtime import WorkerRuntime

@pytest.mark.asyncio
async def test_worker_runtime_basic_chat():
    runtime = WorkerRuntime()
    session = await runtime.session_open("s1")

    events = []
    async def emit(event, payload):
        events.append((event, payload))

    await runtime.user_message(session, "hello computer", None, emit)

    # Check that we got assistant delta and final events
    deltas = [e for e, p in events if e == "assistant.delta"]
    # FIXED: Extract payload (p), not event name (e)
    finals = [p for e, p in events if e == "assistant.final"]

    assert len(deltas) > 0
    assert len(finals) == 1
    assert "Assistant: hello computer" in finals[0]["text"]

@pytest.mark.asyncio
async def test_worker_runtime_triggers_tool_on_keyword():
    runtime = WorkerRuntime()
    session = await runtime.session_open("s1")

    events = []
    async def emit(event, payload):
        events.append((event, payload))

    # The word "tool" should trigger the hardcoded tool logic in WorkerRuntime
    await runtime.user_message(session, "please use a tool for me", None, emit)

    tool_calls = [p for e, p in events if e == "tool.call"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["tool_name"] == "tools.exec"
    assert tool_calls[0]["payload"]["argv"] == ["echo", "tool-invoked"]

@pytest.mark.asyncio
async def test_worker_skill_execution(monkeypatch):
    runtime = WorkerRuntime()

    # FIXED: Mock the skill loader's load method instead of overwriting self.skills
    mock_skill = MagicMock()
    async def mock_run(payload, emit_event):
        return {"worked": True}
    mock_skill.run = mock_run

    monkeypatch.setattr(runtime.skill_loader, "load", lambda: {"test_skill": mock_skill})

    result = await runtime.skill_run("test_skill", {}, None)
    assert result["worked"] is True