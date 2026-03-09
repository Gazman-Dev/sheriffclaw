from __future__ import annotations

import asyncio
import json
from pathlib import Path

from shared.codex_mcp.client import CodexMCPClient


def test_client_recreates_request_lock_for_new_event_loop(tmp_path):
    client = CodexMCPClient(Path(tmp_path), cwd=tmp_path)

    async def _grab_lock_info() -> tuple[int, int]:
        lock = client._get_request_lock()
        return id(asyncio.get_running_loop()), id(lock)

    first_loop, first_lock = asyncio.run(_grab_lock_info())
    second_loop, second_lock = asyncio.run(_grab_lock_info())

    assert first_loop != second_loop
    assert first_lock != 0
    assert second_lock != 0


class _FakeStdout:
    def __init__(self, lines):
        self._lines = [line if isinstance(line, bytes) else line.encode("utf-8") for line in lines]

    async def readline(self):
        if not self._lines:
            return b""
        return self._lines.pop(0)


class _FakeStdin:
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(data)

    async def drain(self):
        return None


class _FakeProc:
    def __init__(self, stdout_lines):
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(stdout_lines)
        self.stderr = None
        self.returncode = None
        self.pid = 123


def test_client_uses_json_line_framing_for_send_and_recv(tmp_path):
    client = CodexMCPClient(Path(tmp_path), cwd=tmp_path)
    client.proc = _FakeProc(
        [
            b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05"}}\n',
        ]
    )

    async def _run():
        result = await client._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        return result, client.proc.stdin.writes[0]

    result, written = asyncio.run(_run())

    assert result["protocolVersion"] == "2024-11-05"
    sent = json.loads(written.decode("utf-8").strip())
    assert sent["method"] == "initialize"
