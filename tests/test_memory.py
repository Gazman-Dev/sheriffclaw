from pathlib import Path

import asyncio

from python_openclaw.memory.sessions import SessionManager
from python_openclaw.memory.workspace import WorkspaceLoader


def test_workspace_loader_reads_files(tmp_path: Path):
    (tmp_path / "SOUL.md").write_text("soul", encoding="utf-8")
    (tmp_path / "USER.md").write_text("user", encoding="utf-8")
    ctx = WorkspaceLoader(tmp_path).load()
    assert "soul" in ctx.system_prompt()


def test_workspace_loader_reload_on_mtime_change(tmp_path: Path):
    soul_path = tmp_path / "SOUL.md"
    soul_path.write_text("v1", encoding="utf-8")
    loader = WorkspaceLoader(tmp_path)
    assert "v1" in loader.load().system_prompt()
    soul_path.write_text("v2 updated", encoding="utf-8")
    assert "v2 updated" in loader.load().system_prompt()


def test_session_compaction(tmp_path: Path):
    mgr = SessionManager(tmp_path, config=None)
    for i in range(200):
        mgr.append("a:b", {"role": "user", "content": "x" * 1000, "i": i})
    compacted = asyncio.run(mgr.maybe_compact("a:b", lambda events: f"summary:{len(events)}"))
    assert compacted is True
