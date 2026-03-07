from __future__ import annotations

import os
import sys
from pathlib import Path


def debug_enabled() -> bool:
    return os.environ.get("SHERIFF_DEBUG", "").strip().lower() in {"1", "true", "yes"}


def debug_script(repo_root: Path) -> Path:
    return repo_root / "debug" / "codex" / "codex_debug.py"


def build_chat_command(repo_root: Path) -> list[str]:
    if debug_enabled():
        return [sys.executable, str(debug_script(repo_root)), "chat", "--dangerously-bypass-approvals-and-sandbox"]
    return ["codex", "chat", "--dangerously-bypass-approvals-and-sandbox"]


def build_login_status_command(repo_root: Path) -> list[str]:
    if debug_enabled():
        return [sys.executable, str(debug_script(repo_root)), "login", "status"]
    return ["codex", "login", "status"]
