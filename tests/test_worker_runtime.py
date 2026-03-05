import pytest

from shared.worker.worker_runtime import WorkerRuntime


@pytest.mark.asyncio
async def test_worker_writes_inbox_file_and_mocks_response(monkeypatch):
    monkeypatch.setenv("SHERIFF_DEBUG", "1")
    rt = WorkerRuntime()

    events = []

    async def emit(event, payload):
        events.append((event, payload))

    h = await rt.session_open("s1")
    await rt.user_message(h, "hello from test", None, emit, channel="telegram", principal_external_id="u1")

    session_dir = rt.conversations_dir / h
    user_files = list(session_dir.glob("*_user_agent.tmd"))
    assert user_files, "expected a user turn file"
    body = user_files[0].read_text(encoding="utf-8")
    assert "hello from test" in body

    agent_files = list(session_dir.glob("*_agent_user.tmd"))
    assert agent_files, "expected an agent simulated response file"
    agent_body = agent_files[0].read_text(encoding="utf-8")
    assert "Mock CLI Response" in agent_body

    finals = [p for e, p in events if e == "assistant.final"]
    assert finals
    assert "Mock CLI Response" in finals[0]["text"]