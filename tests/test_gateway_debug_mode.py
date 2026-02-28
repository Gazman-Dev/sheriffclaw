import pytest

from services.sheriff_gateway.service import SheriffGatewayService


class FakeRPC:
    def __init__(self, handler):
        self._handler = handler

    async def request(self, op, payload, stream_events=False):
        return await self._handler(op, payload, stream_events)


@pytest.mark.asyncio
async def test_debug_mode_tolerates_provider_lookup_error(monkeypatch):
    monkeypatch.setenv("SHERIFF_DEBUG", "1")
    svc = SheriffGatewayService()

    async def ai_stream():
        yield {"event": "assistant.final", "payload": {"text": "ok"}}

    async def ai_request(op, payload, stream_events=False):
        if op == "agent.session.open":
            return [], {"result": {"session_handle": "sess-1"}}
        if op == "agent.session.user_message":
            async def _final():
                return {"ok": True, "result": {}}

            return ai_stream(), _final()
        return [], {"result": {}}

    async def secrets_request(op, payload, stream_events=False):
        if op == "secrets.is_unlocked":
            return [], {"ok": True, "result": {"unlocked": True}}
        if op == "secrets.get_llm_provider":
            return [], {"ok": False, "error": "failed"}
        if op == "secrets.codex_state.get":
            return [], {"ok": True, "result": {"bundle_b64": ""}}
        return [], {"ok": True, "result": {}}

    svc.ai = FakeRPC(ai_request)
    svc.secrets = FakeRPC(secrets_request)

    events = []

    async def emit(ev, payload):
        events.append((ev, payload))

    out = await svc.handle_user_message(
        {"channel": "cli", "principal_external_id": "u1", "text": "hello"},
        emit,
        "r1",
    )

    assert out["status"] == "done"
    assert ("assistant.final", {"text": "ok"}) in events
