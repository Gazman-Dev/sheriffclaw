from __future__ import annotations

import asyncio
from pathlib import Path

from python_openclaw.llm.providers import ModelProvider, NormalizedChunk
from python_openclaw.memory.sessions import SessionManager
from python_openclaw.memory.workspace import WorkspaceLoader
from python_openclaw.security.gate import ApprovalGate
from python_openclaw.security.permissions import PermissionDeniedException, PermissionStore
from python_openclaw.worker.worker_main import Worker


class FakeProvider(ModelProvider):
    def __init__(self):
        super().__init__("k", model_map={"best": "best"}, base_url="http://fake")
        self.calls = 0

    def models_list(self) -> list[str]:
        return ["best"]

    def convert_messages(self, messages: list[dict]) -> dict:
        return {"messages": messages}

    def convert_tools(self, tools: list[dict] | None) -> dict:
        return {}

    def parse_tool_calls(self, payload: dict):
        return []

    async def chat_completion(self, model: str, messages: list[dict], tools=None):
        self.calls += 1
        if self.calls == 1:
            yield NormalizedChunk(content="Need tool", tool_calls=[type("C", (), {"id": "1", "name": "secure.web.request", "arguments": {"host": "a.com"}})()], done=True)
        else:
            yield NormalizedChunk(content="Done", done=True)


def test_worker_permission_denied_waits_for_approval(tmp_path: Path):
    provider = FakeProvider()
    mgr = SessionManager(tmp_path / "sessions")
    loader = WorkspaceLoader(tmp_path)
    (tmp_path / "AGENTS.md").write_text("rules", encoding="utf-8")
    gate = ApprovalGate(PermissionStore(tmp_path / "perm.db"))

    def tool_executor(_event):
        raise PermissionDeniedException("u1", "domain", "a.com")

    worker = Worker(provider=provider, session_manager=mgr, workspace_loader=loader, tool_executor=tool_executor, approval_gate=gate)
    events = asyncio.run(_collect(worker.run("s1", [{"role": "user", "content": "hello"}])))
    assert any(e["stream"] == "tool.result" and e["payload"]["status"] == "waiting_for_approval" for e in events)


async def _collect(iterator):
    out = []
    async for event in iterator:
        out.append(event)
    return out
