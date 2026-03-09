from __future__ import annotations

import os
import subprocess

from shared.paths import agent_repo_root
from shared.worker.codex_cli import augment_path, resolve_codex_binary


def codex_auth_env() -> dict[str, str]:
    env = os.environ.copy()
    env["CODEX_HOME"] = str(agent_repo_root())
    env["PATH"] = augment_path(env.get("PATH"))
    return env


def codex_auth_status() -> dict[str, str | bool]:
    env = codex_auth_env()
    try:
        status = subprocess.run(
            [resolve_codex_binary(), "login", "status"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            cwd=str(agent_repo_root()),
        )
    except FileNotFoundError:
        return {
            "available": False,
            "logged_in": False,
            "detail": "Codex CLI is not installed or not on PATH.",
        }

    detail = ((status.stdout or "") + "\n" + (status.stderr or "")).strip()
    return {
        "available": True,
        "logged_in": status.returncode == 0,
        "detail": detail or ("Logged in." if status.returncode == 0 else "Not logged in."),
    }


def codex_auth_help_text(*, interactive_login_supported: bool) -> str:
    repo_home = str(agent_repo_root())
    if interactive_login_supported:
        return (
            "Codex is not authenticated for this Sheriff repo.\n"
            "Run /auth-login in this terminal chat, or run:\n"
            f"CODEX_HOME={repo_home} codex login"
        )
    return (
        "Codex is not authenticated for this Sheriff repo.\n"
        "Authentication must be completed on the host machine.\n"
        f"Run locally: CODEX_HOME={repo_home} codex login"
    )


def is_codex_auth_error(err: str) -> bool:
    norm = (err or "").lower()
    needles = (
        "401 unauthorized",
        "missing bearer or basic authentication",
        "not logged in",
        "unauthorized",
    )
    return any(needle in norm for needle in needles)
