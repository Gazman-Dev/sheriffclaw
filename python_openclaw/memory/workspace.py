from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class WorkspaceContext:
    agents: str
    soul: str
    user: str

    def system_prompt(self) -> str:
        sections = []
        if self.agents:
            sections.append(f"[AGENTS.md]\n{self.agents}")
        if self.soul:
            sections.append(f"[SOUL.md]\n{self.soul}")
        if self.user:
            sections.append(f"[USER.md]\n{self.user}")
        return "\n\n".join(sections)


class WorkspaceLoader:
    def __init__(self, workspace_dir: Path):
        self.workspace_dir = workspace_dir
        self._cache: dict[str, tuple[float | None, str]] = {}

    def load(self) -> WorkspaceContext:
        return WorkspaceContext(
            agents=self._read_cached("AGENTS.md"),
            soul=self._read_cached("SOUL.md"),
            user=self._read_cached("USER.md"),
        )

    def _read_cached(self, name: str) -> str:
        path = self.workspace_dir / name
        mtime = (path.stat().st_mtime_ns, path.stat().st_size) if path.exists() else None
        cached = self._cache.get(name)
        if cached and cached[0] == mtime:
            return cached[1]
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        self._cache[name] = (mtime, content)
        return content
