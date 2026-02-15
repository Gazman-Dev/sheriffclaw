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

    def load(self) -> WorkspaceContext:
        return WorkspaceContext(
            agents=_read_optional(self.workspace_dir / "AGENTS.md"),
            soul=_read_optional(self.workspace_dir / "SOUL.md"),
            user=_read_optional(self.workspace_dir / "USER.md"),
        )


def _read_optional(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""
