from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from collections import deque
from collections.abc import AsyncIterator
from pathlib import Path

from shared.errors import ProtocolError, ServiceCrashedError
from shared.ndjson import encode_frame
from shared.service_registry import rpc_endpoint


class ProcClient:
    def __init__(self, binary: str, *, cwd=None, env=None, spawn_fallback: bool = True):
        self.binary = binary
        self.cwd = cwd
        self.env = env
        self.spawn_fallback = spawn_fallback
        self.proc: asyncio.subprocess.Process | None = None
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr_tail: deque[str] = deque(maxlen=80)
        self._lock = asyncio.Lock()
        self.request_timeout_sec = float(os.environ.get("SHERIFF_RPC_TIMEOUT_SEC", "600"))

    async def start(self):
        if self.writer is not None and not self.writer.is_closing():
            return
        if self.proc and self.proc.returncode is None:
            return
        endpoint = rpc_endpoint(self.binary)
        if endpoint is not None:
            try:
                self.reader, self.writer = await asyncio.open_connection(*endpoint)
                return
            except OSError as exc:
                self.reader = None
                self.writer = None
                if not self.spawn_fallback:
                    raise ServiceCrashedError(
                        f"managed service unavailable: {self.binary} at {endpoint[0]}:{endpoint[1]} ({exc})"
                    ) from exc
        binary = self.binary
        candidate = Path(sys.executable).parent / self.binary
        if candidate.exists():
            binary = str(candidate)

        self.proc = await asyncio.create_subprocess_exec(
            binary,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=10 * 1024 * 1024,  # Increase limit to 10MB to handle large payloads
            cwd=self.cwd,
            env=self.env,
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self):
        assert self.proc and self.proc.stderr
        while True:
            try:
                line = await self.proc.stderr.readline()
                if not line:
                    return
                self._stderr_tail.append(line.decode("utf-8", errors="replace").rstrip())
            except ValueError:
                # Ignore limit overrun errors in stderr draining if they somehow happen
                continue

    async def _read_frame(self) -> dict:
        if self.reader is not None:
            line = await self.reader.readline()
            if not line:
                raise ServiceCrashedError(f"service connection closed: {self.binary}")
            return json.loads(line.decode("utf-8"))
        assert self.proc and self.proc.stdout
        line = await self.proc.stdout.readline()
        if not line:
            raise ServiceCrashedError("service exited; stderr tail:\n" + "\n".join(self._stderr_tail))
        return json.loads(line.decode("utf-8"))

    async def close(self) -> None:
        reader = self.reader
        writer = self.writer
        proc = self.proc
        stderr_task = self._stderr_task
        self.reader = None
        self.writer = None
        self.proc = None
        self._stderr_task = None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        if reader is not None and writer is None:
            self.reader = None
        if proc is None:
            return

        for stream_name in ("stdin", "stdout", "stderr"):
            stream = getattr(proc, stream_name, None)
            if stream is None:
                continue
            try:
                stream.close()
            except Exception:
                pass

        if proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=1.0)
                except Exception:
                    pass

        if stderr_task is not None:
            stderr_task.cancel()
            try:
                await stderr_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

    async def request(self, op: str, payload: dict, *, stream_events: bool = False):
        await self.start()
        async with self._lock:
            req_id = str(uuid.uuid4())
            if self.writer is not None:
                self.writer.write(encode_frame({"id": req_id, "op": op, "payload": payload}))
                await self.writer.drain()
            else:
                assert self.proc and self.proc.stdin
                self.proc.stdin.write(encode_frame({"id": req_id, "op": op, "payload": payload}))
                await self.proc.stdin.drain()

            if not stream_events:
                events = []
                while True:
                    try:
                        frame = await asyncio.wait_for(self._read_frame(), timeout=self.request_timeout_sec)
                    except asyncio.TimeoutError as e:
                        raise ServiceCrashedError(
                            f"rpc timeout waiting for {self.binary}:{op} after {self.request_timeout_sec:.0f}s; stderr tail:\n"
                            + "\n".join(self._stderr_tail)
                        ) from e
                    if frame.get("id") != req_id:
                        raise ProtocolError(f"unexpected frame id {frame.get('id')} expected {req_id}")
                    if "event" in frame:
                        events.append(frame)
                        continue
                    return events, frame

            frames: list[dict] = []
            final = None
            while True:
                try:
                    frame = await asyncio.wait_for(self._read_frame(), timeout=self.request_timeout_sec)
                except asyncio.TimeoutError as e:
                    raise ServiceCrashedError(
                        f"rpc timeout waiting for {self.binary}:{op} after {self.request_timeout_sec:.0f}s; stderr tail:\n"
                        + "\n".join(self._stderr_tail)
                    ) from e
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
