from __future__ import annotations

import os
import shutil
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
    root = base_root() / "agents" / "codex"
    root.mkdir(parents=True, exist_ok=True)

    def _copy_missing_tree(src: Path, dst: Path) -> None:
        for item in src.rglob("*"):
            rel = item.relative_to(src)
            rel_parts = rel.parts
            if len(rel_parts) >= 2 and rel_parts[0] == "conversations" and rel_parts[1] == "sessions":
                continue
            target = dst / rel
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)

    source_candidates = [
        # Installer-managed source checkout location.
        base_root() / "source" / "agents" / "codex",
        # Developer checkout location.
        Path(__file__).resolve().parents[1] / "agents" / "codex",
    ]
    for src in source_candidates:
        if src.exists():
            _copy_missing_tree(src, root)
            break

    # Ensure minimal runtime folders always exist.
    for rel in (".codex", "conversations/sessions", "skill", "tmp"):
        (root / rel).mkdir(parents=True, exist_ok=True)

    return root
