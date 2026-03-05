from __future__ import annotations

import os
from pathlib import Path


def base_root() -> Path:
    root = os.environ.get("SHERIFFCLAW_ROOT")
    return Path(root).expanduser() if root else Path.home() / ".sheriffclaw"


def _ensure_island(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for child in ("run", "logs", "state"):
        (root / child).mkdir(parents=True, exist_ok=True)
    return root


def gw_root() -> Path:
    return _ensure_island(base_root() / "gw")


def llm_root() -> Path:
    return _ensure_island(base_root() / "llm")


def agent_root() -> Path:
    project_root = Path(__file__).resolve().parents[1]
    root = project_root / "agents" / "codex"
    root.mkdir(parents=True, exist_ok=True)
    return root
