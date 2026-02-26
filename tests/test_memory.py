import pytest
from shared.worker.worker_runtime import WorkerRuntime

@pytest.mark.asyncio
async def test_worker_session_open_close(tmp_path):
    runtime = WorkerRuntime()
    runtime.memory_dir = tmp_path / ".memory"
    runtime.memory_dir.mkdir()
    runtime.session_file = runtime.memory_dir / "session.json"

    handle = await runtime.session_open("test-session")
    assert handle == "primary_session"
    assert "primary_session" in runtime.sessions

    await runtime.session_close(handle)
    assert "primary_session" not in runtime.sessions

@pytest.mark.asyncio
async def test_worker_generates_primary_session_for_empty(tmp_path):
    runtime = WorkerRuntime()
    runtime.memory_dir = tmp_path / ".memory"
    runtime.memory_dir.mkdir()
    runtime.session_file = runtime.memory_dir / "session.json"

    handle = await runtime.session_open(None)
    assert handle == "primary_session"
    assert handle in runtime.sessions

@pytest.mark.asyncio
async def test_worker_history_accumulation(tmp_path):
    runtime = WorkerRuntime()
    runtime.memory_dir = tmp_path / ".memory"
    runtime.memory_dir.mkdir()
    runtime.session_file = runtime.memory_dir / "session.json"

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

    # Verify persistent state saved to disk
    persisted = runtime._load_session(handle)
    assert len(persisted) == 2
    assert persisted[0]["role"] == "user"

@pytest.mark.asyncio
async def test_tool_result_appending(tmp_path):
    runtime = WorkerRuntime()
    runtime.memory_dir = tmp_path / ".memory"
    runtime.memory_dir.mkdir()
    runtime.session_file = runtime.memory_dir / "session.json"

    handle = await runtime.session_open("tool-test")

    await runtime.tool_result(handle, "my_tool", {"status": "ok"})

    history = runtime.sessions[handle]
    assert len(history) == 1
    assert history[0]["role"] == "tool"
    assert history[0]["name"] == "my_tool"
    assert "ok" in history[0]["content"]