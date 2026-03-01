
import pytest

from shared.worker.worker_runtime import WorkerRuntime


@pytest.mark.asyncio
async def test_worker_writes_inbox_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()

    async def emit(event, payload):
        return None

    h = await rt.session_open("s1")
    await rt.user_message(h, "hello", None, emit, channel="telegram", principal_external_id="u1")

    files = list((rt.conversation_dir / h).glob("*_user.md"))
    assert files, "expected a user turn file"
    body = files[0].read_text(encoding="utf-8")
    assert "hello" in body
    assert "channel: telegram" in body


@pytest.mark.asyncio
async def test_worker_dispatches_preexisting_zerozero_files(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    h = await rt.session_open("s1")
    session_dir = rt.conversation_dir / h
    session_dir.mkdir(parents=True, exist_ok=True)
    msg_file = session_dir / "00_2026_03_01_13_25_assistant.md"
    msg_file.write_text("from file", encoding="utf-8")

    events = []

    async def emit(event, payload):
        events.append((event, payload))

    await rt.user_message(h, "hi", None, emit)

    finals = [p for e, p in events if e == "assistant.final"]
    assert finals
    assert "from file" in finals[0]["text"]


@pytest.mark.asyncio
async def test_worker_emits_tool_call_for_test_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    monkeypatch.setenv("SHERIFF_DEBUG", "1")
    rt = WorkerRuntime()
    h = await rt.session_open("s1")

    events = []

    async def emit(event, payload):
        events.append((event, payload))

    await rt.user_message(h, "scenario secret gh_token", None, emit)

    tool_calls = [p for e, p in events if e == "tool.call"]
    assert tool_calls
    assert tool_calls[0]["tool_name"] == "secure.secret.ensure"


@pytest.mark.asyncio
async def test_worker_writes_assistant_response_file_when_no_ready_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    h = await rt.session_open("s1")
    events = []

    async def emit(event, payload):
        events.append((event, payload))

    await rt.user_message(h, "hello world", None, emit)
    session_dir = rt.conversation_dir / h
    assistant_files = list(session_dir.glob("00_*_assistant.md"))
    assert assistant_files, "expected assistant response file"
    text = assistant_files[0].read_text(encoding="utf-8")
    assert "hello world" in text


@pytest.mark.asyncio
async def test_spawn_budget_limit_enforced(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    h = await rt.session_open("s1")

    class _Prov:
        async def generate(self, messages, model="x"):
            return "ok"

    out = []
    for _ in range(4):
        out.append(
            await rt._spawn_child_agent(
                parent_session=h,
                model="stub",
                provider=_Prov(),
                payload={"task": "x", "output_dir": str(tmp_path / "o")},
            )
        )
    assert out[0]["status"] == "ok"
    assert out[1]["status"] == "ok"
    assert out[2]["status"] == "ok"
    assert out[3]["status"] == "error"
    assert out[3]["error"] == "spawn_limit_exceeded"
