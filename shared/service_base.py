from __future__ import annotations

import asyncio
import json
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
        self.ops = dict(ops)
        self.ops.setdefault("meta", self._meta)
        self.ops.setdefault("health", self._health)

    async def _meta(self, payload: dict, emit_event, req_id: str) -> dict:
        return {"name": self.name, "island": self.island, "kind": self.kind, "version": self.version, "ops": sorted(self.ops.keys())}

    async def _health(self, payload: dict, emit_event, req_id: str) -> dict:
        return {"status": "ok"}

    async def run_stdio(self) -> None:
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)
        stdout = sys.stdout.buffer

        async def emit(req_id: str, event_name: str, payload: dict) -> None:
            stdout.write(encode_frame({"id": req_id, "event": event_name, "payload": payload}))
            stdout.flush()

        while True:
            line = await reader.readline()
            if not line:
                return
            if not line.strip():
                continue
            text = line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else line
            req = json.loads(text)
            req_id = req.get("id", "")
            op = req.get("op")
            payload = req.get("payload") or {}
            handler = self.ops.get(op)
            if not handler:
                stdout.write(encode_frame(error_response(req_id, f"unknown op: {op}", "unknown_op")))
                stdout.flush()
                continue
            try:
                result = await handler(payload, lambda e, p: emit(req_id, e, p), req_id)
                stdout.write(encode_frame(ok_response(req_id, result or {})))
            except Exception as exc:  # noqa: BLE001
                print(traceback.format_exc(), file=sys.stderr)
                stdout.write(encode_frame(error_response(req_id, str(exc), exc.__class__.__name__)))
            stdout.flush()
