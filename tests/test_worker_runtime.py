import pytest

from shared.codex_debug import reset_config, save_config
from shared.worker.worker_runtime import WorkerRuntime


@pytest.mark.asyncio
async def test_worker_writes_inbox_file_and_receives_file_protocol_reply(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFF_DEBUG", "1")
    monkeypatch.setenv("SHERIFF_DEBUG_TIMEOUT_SEC", "2")
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    reset_config()
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
    assert agent_files, "expected an agent reply file"
    agent_body = agent_files[0].read_text(encoding="utf-8")
    assert "Debug Codex Response to: hello from test" in agent_body

    finals = [p for e, p in events if e == "assistant.final"]
    assert finals
    assert finals[0]["text"] == "Debug Codex Response to: hello from test"
    await rt.session_close(h)


@pytest.mark.asyncio
async def test_worker_timeout_is_reproducible_via_codex_debug(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFF_DEBUG", "1")
    monkeypatch.setenv("SHERIFF_DEBUG_TIMEOUT_SEC", "0.4")
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    save_config({"chat": "timeout", "login_status": "ok"})
    rt = WorkerRuntime()

    events = []

    async def emit(event, payload):
        events.append((event, payload))

    h = await rt.session_open("s2")
    await rt.user_message(h, "trigger timeout", None, emit, channel="telegram", principal_external_id="u1")

    finals = [p for e, p in events if e == "assistant.final"]
    assert finals[-1]["text"] == "Agent background process response timed out."
    await rt.session_close(h)


@pytest.mark.asyncio
async def test_worker_typing_timeout_emits_delta_before_timeout(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFF_DEBUG", "1")
    monkeypatch.setenv("SHERIFF_DEBUG_TIMEOUT_SEC", "0.5")
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    save_config({"chat": "typing_timeout", "login_status": "ok"})
    rt = WorkerRuntime()

    events = []

    async def emit(event, payload):
        events.append((event, payload))

    h = await rt.session_open("s3")
    await rt.user_message(h, "trigger typing timeout", None, emit, channel="telegram", principal_external_id="u1")

    assert ("assistant.delta", {"text": "typing..."}) in events
    finals = [p for e, p in events if e == "assistant.final"]
    assert finals[-1]["text"] == "Agent background process response timed out."
    await rt.session_close(h)
