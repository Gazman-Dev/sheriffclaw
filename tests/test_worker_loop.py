import pytest
import asyncio
from shared.worker.worker_runtime import WorkerRuntime

@pytest.mark.asyncio
async def test_worker_runtime_tool_trigger():
    runtime = WorkerRuntime()
    events = []
    async def emit(ev, pl):
        events.append((ev, pl))

    # FIXED: await directly instead of asyncio.run()
    handle = await runtime.session_open("s1")
    await runtime.user_message(handle, "please use a tool", None, emit)

    # Check for tool call event
    tool_calls = [e for e in events if e[0] == "tool.call"]
    assert len(tool_calls) > 0
    assert tool_calls[0][1]["tool_name"] == "tools.exec"

@pytest.mark.asyncio
async def test_worker_runtime_basic_chat():
    runtime = WorkerRuntime()
    events = []
    async def emit(ev, pl):
        events.append((ev, pl))

    handle = await runtime.session_open("s1")
    await runtime.user_message(handle, "hello", None, emit)

    assert any(e[0] == "assistant.final" for e in events)