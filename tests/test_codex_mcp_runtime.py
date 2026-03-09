from __future__ import annotations

import asyncio

import pytest

from shared.codex_mcp.client import CodexMCPError
from shared.codex_mcp.runtime import CodexMCPRuntime


class FakeClient:
    def __init__(self, repo_root, *, cwd=None, env=None):
        self.repo_root = repo_root
        self.cwd = cwd
        self.env = env
        self.started = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.started = False

    async def tools_list(self, *, force_refresh=False):
        return [{"name": "codex"}, {"name": "codex-reply"}]

    async def health(self):
        return {"running": self.started, "pid": 100, "initialized": self.started}

    async def codex(self, prompt: str, **kwargs):
        return {"structuredContent": {"threadId": "thread-1", "content": prompt, "kwargs": kwargs}}

    async def codex_reply(self, prompt: str, thread_id: str):
        return {"structuredContent": {"threadId": thread_id, "content": prompt}}


class MissingToolClient(FakeClient):
    async def tools_list(self, *, force_refresh=False):
        return [{"name": "codex"}]


@pytest.mark.asyncio
async def test_runtime_ensure_started_initializes_and_validates_tools(tmp_path):
    runtime = CodexMCPRuntime(tmp_path, cwd=tmp_path, client_factory=FakeClient)

    health = await runtime.ensure_started()

    assert health["running"] is True
    assert health["initialized"] is True
    assert health["tools"] == ["codex", "codex-reply"]


@pytest.mark.asyncio
async def test_runtime_requires_documented_tool_surface(tmp_path):
    runtime = CodexMCPRuntime(tmp_path, cwd=tmp_path, client_factory=MissingToolClient)

    with pytest.raises(CodexMCPError):
        await runtime.ensure_started()


@pytest.mark.asyncio
async def test_runtime_wraps_start_and_reply_calls(tmp_path):
    runtime = CodexMCPRuntime(tmp_path, cwd=tmp_path, client_factory=FakeClient)

    started = await runtime.start_conversation("hello", sandbox="workspace-write")
    replied = await runtime.continue_conversation("again", "thread-1")

    assert started["structuredContent"]["threadId"] == "thread-1"
    assert started["structuredContent"]["kwargs"]["sandbox"] == "workspace-write"
    assert replied["structuredContent"]["threadId"] == "thread-1"


def test_runtime_recreates_lock_for_new_event_loop(tmp_path):
    runtime = CodexMCPRuntime(tmp_path, cwd=tmp_path, client_factory=FakeClient)

    first = asyncio.run(runtime.ensure_started())
    second = asyncio.run(runtime.health())

    assert first["running"] is True
    assert second["running"] is True
