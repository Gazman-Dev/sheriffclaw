from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

from shared.ndjson import encode_frame
from shared.protocol import error_response, ok_response

Handler = Callable[[dict[str, Any], Callable[[str, dict[str, Any]], Awaitable[None]], str], Awaitable[dict[str, Any]]]


class NDJSONService:
    def __init__(self, *, name: str, island: str, kind: str, version: str, ops: dict[str, Handler]):
        self.name = name
        self.island = island
        self.kind = kind
        self.version = version
        self.debug_mode = os.environ.get("SHERIFF_DEBUG", "").strip().lower() in {"1", "true", "yes"}
        self.ops = dict(ops)
        self.ops.setdefault("meta", self._meta)
        self.ops.setdefault("health", self._health)

    async def _meta(self, payload: dict, emit_event, req_id: str) -> dict:
        return {"name": self.name, "island": self.island, "kind": self.kind, "version": self.version,
                "ops": sorted(self.ops.keys())}

    async def _health(self, payload: dict, emit_event, req_id: str) -> dict:
        return {"status": "ok"}

    async def _dispatch_line(
            self,
            text: str,
            *,
            write_frame: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        req = json.loads(text)
        req_id = req.get("id", "")
        op = req.get("op")
        payload = req.get("payload") or {}
        handler = self.ops.get(op)
        if not handler:
            await write_frame(error_response(req_id, f"unknown op: {op}", "unknown_op"))
            return

        async def emit(event_name: str, event_payload: dict[str, Any]) -> None:
            await write_frame({"id": req_id, "event": event_name, "payload": event_payload})

        try:
            result = await handler(payload, emit, req_id)
            await write_frame(ok_response(req_id, result or {}))
        except Exception as exc:  # noqa: BLE001
            print(traceback.format_exc(), file=sys.stderr)
            await write_frame(error_response(req_id, str(exc), exc.__class__.__name__))

    async def run_stdio(self) -> None:
        # Increase line reading limit to 10MB to handle large state payloads (like codex-cli auth bundle)
        reader = asyncio.StreamReader(limit=10 * 1024 * 1024)
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)
        stdout = sys.stdout.buffer

        async def write_frame(frame: dict[str, Any]) -> None:
            stdout.write(encode_frame(frame))
            stdout.flush()

        while True:
            line = await reader.readline()
            if not line:
                return
            if not line.strip():
                continue
            text = line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else line
            await self._dispatch_line(text, write_frame=write_frame)

    async def run_tcp(self, host: str, port: int) -> None:
        async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            async def write_frame(frame: dict[str, Any]) -> None:
                writer.write(encode_frame(frame))
                await writer.drain()

            try:
                while True:
                    line = await reader.readline()
                    if not line:
                        return
                    if not line.strip():
                        continue
                    text = line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else line
                    await self._dispatch_line(text, write_frame=write_frame)
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

        server = await asyncio.start_server(handle_client, host, port)
        async with server:
            await server.serve_forever()
