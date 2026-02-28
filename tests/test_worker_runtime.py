import pytest

pytest.importorskip("hnswlib")
from unittest.mock import AsyncMock
import asyncio
from shared.worker.worker_runtime import WorkerRuntime


@pytest.mark.asyncio
async def test_worker_runtime_basic_chat(tmp_path):
    runtime = WorkerRuntime()
    runtime.memory_dir = tmp_path / ".memory"
    runtime.memory_dir.mkdir()
    runtime.session_file = runtime.memory_dir / "session.json"

    session = await runtime.session_open("s1")

    events =[]

    async def emit(event, payload):
        events.append((event, payload))

    await runtime.user_message(session, "hello computer", None, emit)

    deltas =[e for e, p in events if e == "assistant.delta"]
    finals =[p for e, p in events if e == "assistant.final"]

    assert len(deltas) > 0
    assert len(finals) == 1
    assert "Assistant: hello computer" in finals[0]["text"]


@pytest.mark.asyncio
async def test_worker_runtime_triggers_tool_on_keyword(tmp_path):
    runtime = WorkerRuntime()
    runtime.memory_dir = tmp_path / ".memory"
    runtime.memory_dir.mkdir()
    runtime.session_file = runtime.memory_dir / "session.json"

    session = await runtime.session_open("s1")

    events =[]

    async def emit(event, payload):
        events.append((event, payload))

    await runtime.user_message(session, "please use a tool for me", None, emit)

    tool_calls =[p for e, p in events if e == "tool.call"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["tool_name"] == "tools.exec"
    assert tool_calls[0]["payload"]["argv"] == ["echo", "tool-invoked"]


@pytest.mark.asyncio
async def test_worker_skill_execution(monkeypatch, tmp_path):
    runtime = WorkerRuntime()
    runtime.workspace_root = tmp_path
    (tmp_path / "agent_workspace").mkdir(parents=True)
    runtime.memory_dir = tmp_path / ".memory"
    runtime.memory_dir.mkdir()
    runtime.session_file = runtime.memory_dir / "session.json"

    class MockSkill:
        command = "echo 'worked'"

    monkeypatch.setattr(runtime.skill_loader, "load", lambda: {"test_skill": MockSkill()})

    result = await runtime.skill_run("test_skill", {}, None)
    assert "worked" in result["stdout"]
    assert result["code"] == 0


@pytest.mark.asyncio
async def test_worker_scenario_secret_flow_emits_tool_call(tmp_path):
    runtime = WorkerRuntime()
    runtime.memory_dir = tmp_path / ".memory"
    runtime.memory_dir.mkdir()
    runtime.session_file = runtime.memory_dir / "session.json"

    session = await runtime.session_open("s2")

    events =[]

    async def emit(event, payload):
        events.append((event, payload))

    await runtime.user_message(session, "scenario secret gh_token", "scenario/default", emit)

    tool_calls =[p for e, p in events if e == "tool.call"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["tool_name"] == "secure.secret.ensure"
    assert tool_calls[0]["payload"]["handle"] == "gh_token"


@pytest.mark.asyncio
async def test_worker_scenario_last_tool_reads_history(tmp_path):
    runtime = WorkerRuntime()
    runtime.memory_dir = tmp_path / ".memory"
    runtime.memory_dir.mkdir()
    runtime.session_file = runtime.memory_dir / "session.json"

    session = await runtime.session_open("s3")
    await runtime.tool_result(session, "secure.secret.ensure", {"status": "needs_secret", "handle": "gh_token"})

    events =[]

    async def emit(event, payload):
        events.append((event, payload))

    await runtime.user_message(session, "scenario last tool", "scenario/default", emit)

    finals =[p for e, p in events if e == "assistant.final"]
    assert len(finals) == 1
    assert "needs_secret" in finals[0]["text"]


@pytest.mark.asyncio
async def test_sheriff_call_uses_proc_client(monkeypatch):
    runtime = WorkerRuntime()
    fake = AsyncMock()
    fake.request.return_value = (None, {"result": {"ok": True}})
    monkeypatch.setattr(runtime, "_get_rpc", lambda svc: fake)

    main_loop = asyncio.get_running_loop()

    # Must run the sync wrapper in a separate thread to avoid deadlocking the test loop
    out = await asyncio.to_thread(runtime._sheriff_call_sync, "sheriff-requests", "requests.get", {"x": 1}, main_loop)
    assert out["ok"] is True
    fake.request.assert_called_with("requests.get", {"x": 1})