import pytest
from unittest.mock import MagicMock, AsyncMock
from shared.worker.worker_runtime import WorkerRuntime


@pytest.mark.asyncio
async def test_worker_runtime_basic_chat():
    runtime = WorkerRuntime()
    session = await runtime.session_open("s1")

    events = []

    async def emit(event, payload):
        events.append((event, payload))

    await runtime.user_message(session, "hello computer", None, emit)

    deltas = [e for e, p in events if e == "assistant.delta"]
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

    await runtime.user_message(session, "please use a tool for me", None, emit)

    tool_calls = [p for e, p in events if e == "tool.call"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["tool_name"] == "tools.exec"
    assert tool_calls[0]["payload"]["argv"] == ["echo", "tool-invoked"]


@pytest.mark.asyncio
async def test_worker_skill_execution(monkeypatch):
    runtime = WorkerRuntime()

    class MockSkill:
        async def run(self, payload, emit_event):
            return {"worked": True}

    monkeypatch.setattr(runtime.skill_loader, "load", lambda: {"test_skill": MockSkill()})

    result = await runtime.skill_run("test_skill", {}, None)
    assert result["worked"] is True


@pytest.mark.asyncio
async def test_worker_scenario_secret_flow_emits_tool_call():
    runtime = WorkerRuntime()
    session = await runtime.session_open("s2")

    events = []

    async def emit(event, payload):
        events.append((event, payload))

    await runtime.user_message(session, "scenario secret gh_token", "scenario/default", emit)

    tool_calls = [p for e, p in events if e == "tool.call"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["tool_name"] == "secure.secret.ensure"
    assert tool_calls[0]["payload"]["handle"] == "gh_token"


@pytest.mark.asyncio
async def test_worker_scenario_last_tool_reads_history():
    runtime = WorkerRuntime()
    session = await runtime.session_open("s3")
    await runtime.tool_result(session, "secure.secret.ensure", {"status": "needs_secret", "handle": "gh_token"})

    events = []

    async def emit(event, payload):
        events.append((event, payload))

    await runtime.user_message(session, "scenario last tool", "scenario/default", emit)

    finals = [p for e, p in events if e == "assistant.final"]
    assert len(finals) == 1
    assert "needs_secret" in finals[0]["text"]


@pytest.mark.asyncio
async def test_worker_skill_context_exposes_sheriff_call(monkeypatch):
    runtime = WorkerRuntime()

    async def fake_run(payload, emit_event=None, context=None):
        fn = context["sheriff_call"]
        return {"callable": callable(fn), "source": context["skill_source"]}

    impl = type("Impl", (), {})()
    impl.run = fake_run
    loaded = type("Loaded", (), {"implementation_module": impl, "root": "/tmp", "source": "system"})
    monkeypatch.setattr(runtime.skill_loader, "load", lambda: {"s": loaded})

    out = await runtime.skill_run("s", {}, None)
    assert out["callable"] is True
    assert out["source"] == "system"


@pytest.mark.asyncio
async def test_sheriff_call_blocks_non_sheriff_service():
    runtime = WorkerRuntime()
    with pytest.raises(ValueError):
        await runtime._sheriff_call("ai-worker", "x", {})


@pytest.mark.asyncio
async def test_sheriff_call_uses_proc_client(monkeypatch):
    runtime = WorkerRuntime()
    fake = AsyncMock()
    fake.request.return_value = (None, {"result": {"ok": True}})
    monkeypatch.setattr(runtime, "_rpc_client", lambda svc: fake)

    out = await runtime._sheriff_call("sheriff-requests", "requests.get", {"x": 1})
    assert out["ok"] is True
    fake.request.assert_called_with("requests.get", {"x": 1})
