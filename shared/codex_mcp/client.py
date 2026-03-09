from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from shared.worker.codex_cli import augment_path, build_mcp_server_command


JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2024-11-05"


class CodexMCPError(RuntimeError):
    pass


class CodexMCPClient:
    def __init__(self, repo_root: Path, *, cwd: Path | None = None, env: Mapping[str, str] | None = None) -> None:
        self.repo_root = repo_root
        self.cwd = cwd or repo_root
        self.env = dict(env or {})
        self.proc: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._request_lock: asyncio.Lock | None = None
        self._request_lock_loop: asyncio.AbstractEventLoop | None = None
        self._initialized = False
        self._tools_cache: list[dict[str, Any]] | None = None

    def _get_request_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._request_lock is None or self._request_lock_loop is not loop:
            self._request_lock = asyncio.Lock()
            self._request_lock_loop = loop
        return self._request_lock

    async def start(self) -> None:
        if self.proc and self.proc.returncode is None:
            return
        env = os.environ.copy()
        env.update(self.env)
        env["PATH"] = augment_path(env.get("PATH"))
        cmd = build_mcp_server_command(self.repo_root)
        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.cwd),
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await self.initialize()

    async def stop(self) -> None:
        proc = self.proc
        self.proc = None
        self._initialized = False
        self._tools_cache = None
        if proc is None:
            return
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

    async def initialize(self) -> None:
        if self._initialized:
            return
        result = await self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "sheriffclaw", "version": "migration"},
            },
        )
        protocol = str(result.get("protocolVersion") or "")
        if protocol and protocol != MCP_PROTOCOL_VERSION:
            raise CodexMCPError(f"unexpected MCP protocol version: {protocol}")
        await self._notify("notifications/initialized", {})
        self._initialized = True

    async def tools_list(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        if self._tools_cache is not None and not force_refresh:
            return list(self._tools_cache)
        result = await self._request("tools/list", {})
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise CodexMCPError("invalid tools/list response")
        self._tools_cache = [tool for tool in tools if isinstance(tool, dict)]
        return list(self._tools_cache)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._request("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict):
            raise CodexMCPError("invalid tools/call response")
        return result

    async def codex(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        payload = {"prompt": prompt, **kwargs}
        return await self.call_tool("codex", payload)

    async def codex_reply(self, prompt: str, thread_id: str) -> dict[str, Any]:
        return await self.call_tool("codex-reply", {"prompt": prompt, "threadId": thread_id})

    async def health(self) -> dict[str, Any]:
        proc = self.proc
        return {
            "running": bool(proc and proc.returncode is None),
            "pid": proc.pid if proc else None,
            "initialized": self._initialized,
            "cwd": str(self.cwd),
        }

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send({"jsonrpc": JSONRPC_VERSION, "method": method, "params": params})

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        async with self._get_request_lock():
            self._request_id += 1
            req_id = self._request_id
            await self._send({"jsonrpc": JSONRPC_VERSION, "id": req_id, "method": method, "params": params})
            while True:
                message = await self._recv()
                if "id" not in message:
                    continue
                if message.get("id") != req_id:
                    raise CodexMCPError(f"unexpected response id: {message.get('id')}")
                if "error" in message:
                    error = message["error"]
                    if isinstance(error, dict):
                        detail = error.get("message") or json.dumps(error, ensure_ascii=True)
                    else:
                        detail = str(error)
                    raise CodexMCPError(detail)
                result = message.get("result", {})
                if not isinstance(result, dict):
                    raise CodexMCPError("invalid JSON-RPC result payload")
                return result

    async def _send(self, payload: dict[str, Any]) -> None:
        proc = self.proc
        if proc is None or proc.stdin is None:
            raise CodexMCPError("mcp process is not running")
        body = (json.dumps(payload, ensure_ascii=True) + "\n").encode("utf-8")
        proc.stdin.write(body)
        await proc.stdin.drain()

    async def _recv(self) -> dict[str, Any]:
        proc = self.proc
        if proc is None or proc.stdout is None:
            raise CodexMCPError("mcp process is not running")
        while True:
            line = await proc.stdout.readline()
            if not line:
                stderr_text = await self._read_stderr_tail()
                raise CodexMCPError(f"mcp process closed unexpectedly: {stderr_text}")
            stripped = line.strip()
            if not stripped:
                continue
            try:
                message = json.loads(stripped.decode("utf-8"))
            except json.JSONDecodeError:
                # Ignore non-JSON noise if Codex emits it on stdout.
                continue
            break
        if not isinstance(message, dict):
            raise CodexMCPError("invalid JSON-RPC message")
        return message

    async def _read_stderr_tail(self) -> str:
        proc = self.proc
        if proc is None or proc.stderr is None:
            return "(stderr unavailable)"
        try:
            data = await asyncio.wait_for(proc.stderr.read(), timeout=0.05)
        except Exception:
            return "(stderr unavailable)"
        text = data.decode("utf-8", errors="replace").strip()
        return text[-400:] if text else "(no stderr output)"
