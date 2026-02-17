import pytest
from shared.worker.worker_runtime import WorkerRuntime

@pytest.mark.asyncio
async def test_worker_session_open_close():
    runtime = WorkerRuntime()
    handle = await runtime.session_open("test-session")
    assert handle == "test-session"
    assert "test-session" in runtime.sessions

    await runtime.session_close(handle)
    assert "test-session" not in runtime.sessions

@pytest.mark.asyncio
async def test_worker_generates_uuid_for_empty_session():
    runtime = WorkerRuntime()
    handle = await runtime.session_open(None)
    assert handle
    assert isinstance(handle, str)
    assert handle in runtime.sessions

@pytest.mark.asyncio
async def test_worker_history_accumulation():
    runtime = WorkerRuntime()
    handle = await runtime.session_open("history-test")

    async def noop_emit(event, payload):
        pass

    # Sending a message adds user message + assistant reply to history
    await runtime.user_message(handle, "hello", None, noop_emit)

    history = runtime.sessions[handle]
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "hello"
    assert history[1]["role"] == "assistant"

@pytest.mark.asyncio
async def test_tool_result_appending():
    runtime = WorkerRuntime()
    handle = await runtime.session_open("tool-test")

    await runtime.tool_result(handle, "my_tool", {"status": "ok"})

    history = runtime.sessions[handle]
    assert len(history) == 1
    assert history[0]["role"] == "tool"
    assert history[0]["name"] == "my_tool"
    assert "ok" in history[0]["content"]