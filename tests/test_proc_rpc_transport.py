from __future__ import annotations

import asyncio
import socket

import pytest

from shared.proc_rpc import ProcClient
from shared.service_base import NDJSONService


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.mark.asyncio
async def test_proc_client_connects_to_daemon_tcp(monkeypatch):
    port = _free_port()
    app = NDJSONService(
        name="test",
        island="gw",
        kind="service",
        version="1",
        ops={"echo": lambda payload, emit, req_id: asyncio.sleep(0, result={"echo": payload["text"]})},
    )
    server_task = asyncio.create_task(app.run_tcp("127.0.0.1", port))
    await asyncio.sleep(0.1)
    monkeypatch.setattr("shared.proc_rpc.rpc_endpoint", lambda service: ("127.0.0.1", port) if service == "dummy" else None)
    client = ProcClient("dummy", spawn_fallback=False)
    try:
        _, res = await client.request("echo", {"text": "hello"})
        assert res["result"]["echo"] == "hello"
    finally:
        await client.close()
        server_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await server_task


@pytest.mark.asyncio
async def test_proc_client_daemon_only_raises_when_service_unavailable(monkeypatch):
    port = _free_port()
    monkeypatch.setattr("shared.proc_rpc.rpc_endpoint", lambda service: ("127.0.0.1", port) if service == "dummy" else None)
    client = ProcClient("dummy", spawn_fallback=False)
    with pytest.raises(Exception):
        await client.request("echo", {"text": "hello"})


def test_proc_client_can_be_constructed_outside_loop_and_used_inside(monkeypatch):
    port = _free_port()
    client = ProcClient("dummy", spawn_fallback=False)

    async def _run():
        app = NDJSONService(
            name="test",
            island="gw",
            kind="service",
            version="1",
            ops={"echo": lambda payload, emit, req_id: asyncio.sleep(0, result={"echo": payload["text"]})},
        )
        server_task = asyncio.create_task(app.run_tcp("127.0.0.1", port))
        await asyncio.sleep(0.1)
        monkeypatch.setattr("shared.proc_rpc.rpc_endpoint", lambda service: ("127.0.0.1", port) if service == "dummy" else None)
        try:
            _, res = await client.request("echo", {"text": "hello"})
            assert res["result"]["echo"] == "hello"
        finally:
            await client.close()
            server_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await server_task

    asyncio.run(_run())


def test_rpc_endpoint_is_none_for_non_rpc_listener():
    from shared.service_registry import rpc_endpoint

    assert rpc_endpoint("telegram-listener") is None
