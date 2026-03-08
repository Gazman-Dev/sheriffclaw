from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from services.sheriff_chat_proxy.service import SheriffChatProxyService


@pytest.mark.asyncio
async def test_chat_proxy_forwards_stream_events():
    svc = SheriffChatProxyService()

    async def _stream():
        yield {"event": "assistant.final", "payload": {"text": "hi"}}

    fut = asyncio.get_running_loop().create_future()
    fut.set_result({"result": {"status": "done"}})
    svc.gateway.request = AsyncMock(return_value=(_stream(), fut))
    events = []

    async def emit(event, payload):
        events.append((event, payload))

    out = await svc.send({"text": "hello"}, emit, "r1")
    assert ("assistant.final", {"text": "hi"}) in events
    assert out["status"] == "done"
