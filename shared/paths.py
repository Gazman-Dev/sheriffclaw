from __future__ import annotations

import os
from pathlib import Path


_DEFAULT_AGENTS_BODY = (
    "# SheriffClaw Agent Instructions\n\n"
    "The repo is the durable source of truth. Preserve raw user meaning and do not rely on host-written wrappers.\n"
)


def base_root() -> Path:
    root = os.environ.get("SHERIFFCLAW_ROOT")
    return Path(root).expanduser() if root else Path.home() / ".sheriffclaw"


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ensure_island(root: Path) -> Path:
    _ensure_dir(root)
    for child in ("run", "logs", "state"):
        _ensure_dir(root / child)
    return root


def gw_root() -> Path:
    return _ensure_island(base_root() / "gw")


def llm_root() -> Path:
    return _ensure_island(base_root() / "llm")


def agent_repo_root() -> Path:
    root = _ensure_dir(base_root() / "agent_repo")
    for child in ("memory", "tasks", "sessions", "skills", "system", "logs", ".codex"):
        _ensure_dir(root / child)
    defaults = {
        "AGENTS.md": _DEFAULT_AGENTS_BODY,
        "config.toml": "",
        ".codex/config.toml": "",
        "README.md": "# Agent Repo\n",
    }
    for rel, body in defaults.items():
        target = root / rel
        if not target.exists():
            target.write_text(body, encoding="utf-8")
    return root


def agent_root() -> Path:
    # Deprecated compatibility alias during migration. The repo-backed agent root is the only supported state root.
    return agent_repo_root()
