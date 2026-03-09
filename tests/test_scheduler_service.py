from __future__ import annotations

import json

import pytest

from services.sheriff_scheduler.service import SheriffSchedulerService


class FakeRPC:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def request(self, op, payload, stream_events=False):
        self.calls.append((op, payload, stream_events))
        handler = self.responses[op]
        return await handler(payload, stream_events)


def _make_service(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    svc = SheriffSchedulerService()
    return svc


@pytest.mark.asyncio
async def test_scheduler_runs_due_heartbeat_and_updates_state(monkeypatch, tmp_path):
    svc = _make_service(monkeypatch, tmp_path)

    async def queue_status(payload, stream_events):
        return [], {"result": {"processing": 0}}

    async def session_ensure(payload, stream_events):
        return [], {"result": {"session": {"session_key": payload["session_key"]}}}

    async def session_send(payload, stream_events):
        async def _stream():
            yield {"event": "assistant.final", "payload": {"text": "heartbeat done"}}
        return _stream(), {"result": {"status": "done"}}

    svc.gateway = FakeRPC({"gateway.queue.status": queue_status})
    svc.ai = FakeRPC({"codex.session.ensure": session_ensure, "codex.session.send": session_send})

    result = await svc._run_due_jobs(force=True)

    assert result["heartbeat"]["status"] == "ran"
    state = json.loads((tmp_path / "agent_repo" / "system" / "maintenance_state.json").read_text(encoding="utf-8"))
    assert state["heartbeat"]["last_result"] == "heartbeat done"


@pytest.mark.asyncio
async def test_scheduler_skips_job_when_gateway_busy(monkeypatch, tmp_path):
    svc = _make_service(monkeypatch, tmp_path)

    async def queue_status(payload, stream_events):
        return [], {"result": {"processing": 1}}

    async def session_ensure(payload, stream_events):
        return [], {"result": {}}

    async def session_send(payload, stream_events):
        async def _stream():
            if False:
                yield {}
        return _stream(), {"result": {"status": "done"}}

    svc.gateway = FakeRPC({"gateway.queue.status": queue_status})
    svc.ai = FakeRPC({"codex.session.ensure": session_ensure, "codex.session.send": session_send})

    result = await svc._run_job("heartbeat", svc._load_state())

    assert result == {"status": "skipped", "reason": "gateway_busy"}


@pytest.mark.asyncio
async def test_scheduler_build_job_prompt_includes_tasks(monkeypatch, tmp_path):
    svc = _make_service(monkeypatch, tmp_path)
    svc.task_store.create_task(title="Follow up", session_key="private_main")
    sessions_path = tmp_path / "agent_repo" / "sessions" / "sessions.json"
    payload = json.loads(sessions_path.read_text(encoding="utf-8"))
    payload["sessions"]["private_main"] = {"session_key": "private_main"}
    sessions_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    prompt = svc._build_job_prompt("heartbeat")

    assert "Run the periodic heartbeat maintenance skill" in prompt
    assert "Follow up" in prompt
    assert "Inspect repo-backed memory, summaries, sessions, and tasks" in prompt
    assert "- private_main" in prompt
    assert "- memory/inbox.md" in prompt
