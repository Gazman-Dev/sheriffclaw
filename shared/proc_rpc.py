from __future__ import annotations

import asyncio
import json
import sys
import uuid
from collections import deque
from collections.abc import AsyncIterator
from pathlib import Path

from shared.errors import ProtocolError, ServiceCrashedError
from shared.ndjson import encode_frame


class ProcClient:
    def __init__(self, binary: str, *, cwd=None, env=None):
        self.binary = binary
        self.cwd = cwd
        self.env = env
        self.proc: asyncio.subprocess.Process | None = None
        self._stderr_tail: deque[str] = deque(maxlen=80)
        self._lock = asyncio.Lock()

    async def start(self):
        if self.proc and self.proc.returncode is None:
            return
        binary = self.binary
        candidate = Path(sys.executable).parent / self.binary
        if candidate.exists():
            binary = str(candidate)

        self.proc = await asyncio.create_subprocess_exec(
            binary,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
            env=self.env,
        )
        asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self):
        assert self.proc and self.proc.stderr
        while True:
            line = await self.proc.stderr.readline()
            if not line:
                return
            self._stderr_tail.append(line.decode("utf-8", errors="replace").rstrip())

    async def _read_frame(self) -> dict:
        assert self.proc and self.proc.stdout
        line = await self.proc.stdout.readline()
        if not line:
            raise ServiceCrashedError("service exited; stderr tail:\n" + "\n".join(self._stderr_tail))
        return json.loads(line.decode("utf-8"))

    async def request(self, op: str, payload: dict, *, stream_events: bool = False):
        await self.start()
        async with self._lock:
            assert self.proc and self.proc.stdin
            req_id = str(uuid.uuid4())
            self.proc.stdin.write(encode_frame({"id": req_id, "op": op, "payload": payload}))
            await self.proc.stdin.drain()

            if not stream_events:
                events = []
                while True:
                    frame = await self._read_frame()
                    if frame.get("id") != req_id:
                        raise ProtocolError(f"unexpected frame id {frame.get('id')} expected {req_id}")
                    if "event" in frame:
                        events.append(frame)
                        continue
                    return events, frame

            frames: list[dict] = []
            final = None
            while True:
                frame = await self._read_frame()
                if frame.get("id") != req_id:
                    raise ProtocolError(f"unexpected frame id {frame.get('id')} expected {req_id}")
                if "event" in frame:
                    frames.append(frame)
                    continue
                final = frame
                break

            async def _iterate() -> AsyncIterator[dict]:
                for frame in frames:
                    yield frame

            fut = asyncio.get_running_loop().create_future()
            fut.set_result(final)
            return _iterate(), fut
