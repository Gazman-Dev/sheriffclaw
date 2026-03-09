from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from shared.agent_repo import ensure_layout
from shared.codex_mcp.client import CodexMCPClient, CodexMCPError
from shared.paths import agent_repo_root


class CodexMCPRuntime:
    def __init__(
        self,
        repo_root: Path,
        *,
        cwd: Path | None = None,
        client_factory: Callable[..., CodexMCPClient] = CodexMCPClient,
    ) -> None:
        self.repo_root = repo_root
        self.cwd = cwd or agent_repo_root()
        self.client_factory = client_factory
        self.client: CodexMCPClient | None = None
        self.started_at: float | None = None
        self.tools: set[str] = set()
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    async def ensure_started(self) -> dict[str, Any]:
        async with self._get_lock():
            if self.client is None:
                ensure_layout()
                self.client = self.client_factory(self.repo_root, cwd=self.cwd)
                await self.client.start()
                self.started_at = time.time()
                await self._refresh_tools()
            return await self.health()

    async def stop(self) -> None:
        async with self._get_lock():
            if self.client is not None:
                await self.client.stop()
            self.client = None
            self.tools = set()
            self.started_at = None

    async def health(self) -> dict[str, Any]:
        client = self.client
        base = {"started_at": self.started_at, "tools": sorted(self.tools), "cwd": str(self.cwd)}
        if client is None:
            return {"running": False, "initialized": False, "pid": None, **base}
        return {**base, **(await client.health())}

    async def start_conversation(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        client = await self._require_client()
        return await client.codex(prompt, **kwargs)

    async def continue_conversation(self, prompt: str, thread_id: str) -> dict[str, Any]:
        client = await self._require_client()
        return await client.codex_reply(prompt, thread_id)

    async def _require_client(self) -> CodexMCPClient:
        await self.ensure_started()
        assert self.client is not None
        return self.client

    async def _refresh_tools(self) -> None:
        assert self.client is not None
        tools = await self.client.tools_list(force_refresh=True)
        names = {str(tool.get("name") or "") for tool in tools}
        missing = {"codex", "codex-reply"} - names
        if missing:
            raise CodexMCPError(f"missing required MCP tools: {sorted(missing)}")
        self.tools = names
