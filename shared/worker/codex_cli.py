from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path


def debug_enabled() -> bool:
    return os.environ.get("SHERIFF_DEBUG", "").strip().lower() in {"1", "true", "yes"}


def debug_script(repo_root: Path) -> Path:
    return repo_root / "debug" / "codex" / "codex_debug.py"


def resolve_codex_binary() -> str:
    explicit = os.environ.get("CODEX_BIN", "").strip()
    if explicit:
        return explicit

    found = shutil.which("codex")
    if found:
        return found

    home = Path.home()
    candidates = [
        Path("/opt/homebrew/bin/codex"),
        Path("/usr/local/bin/codex"),
        home / ".local" / "bin" / "codex",
        home / ".npm" / "bin" / "codex",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return "codex"


def augment_path(path_value: str | None) -> str:
    parts = [p for p in (path_value or "").split(os.pathsep) if p]
    home = str(Path.home())
    candidates = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        os.path.join(home, ".local", "bin"),
        os.path.join(home, ".npm", "bin"),
    ]
    for candidate in candidates:
        if candidate and candidate not in parts:
            parts.append(candidate)
    return os.pathsep.join(parts)


def build_chat_command(repo_root: Path) -> list[str]:
    if debug_enabled():
        return [sys.executable, str(debug_script(repo_root)), "chat", "--dangerously-bypass-approvals-and-sandbox"]
    codex = resolve_codex_binary()
    if platform.system() == "Darwin":
        script_bin = shutil.which("script") or "/usr/bin/script"
        if Path(script_bin).exists():
            return [script_bin, "-q", "/dev/null", codex, "chat", "--dangerously-bypass-approvals-and-sandbox"]
    return [codex, "chat", "--dangerously-bypass-approvals-and-sandbox"]


def build_login_status_command(repo_root: Path) -> list[str]:
    if debug_enabled():
        return [sys.executable, str(debug_script(repo_root)), "login", "status"]
    return [resolve_codex_binary(), "login", "status"]
