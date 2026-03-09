from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from shared.paths import agent_repo_root
from shared.worker.codex_cli import augment_path, resolve_codex_binary


def _auth_file() -> Path:
    return agent_repo_root() / "auth.json"


def _device_auth_state_file() -> Path:
    return agent_repo_root() / "system" / "codex_device_auth.json"


def _device_auth_log_file() -> Path:
    return agent_repo_root() / "system" / "codex_device_auth.log"


def codex_auth_env() -> dict[str, str]:
    env = os.environ.copy()
    env["CODEX_HOME"] = str(agent_repo_root())
    env["PATH"] = augment_path(env.get("PATH"))
    return env


def _jwt_expiry_epoch(token: str | None) -> int | None:
    if not token or token.count(".") < 2:
        return None
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
    except Exception:
        return None
    exp = data.get("exp")
    return int(exp) if isinstance(exp, (int, float)) else None


def repair_codex_auth_permissions() -> None:
    auth_file = _auth_file()
    if not auth_file.exists():
        return
    try:
        os.chmod(auth_file, 0o640)
    except Exception:
        pass


def _load_auth_payload() -> dict:
    auth_file = _auth_file()
    if not auth_file.exists():
        return {}
    repair_codex_auth_permissions()
    try:
        return json.loads(auth_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _device_auth_state() -> dict:
    path = _device_auth_state_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_device_auth_state(payload: dict) -> None:
    path = _device_auth_state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _clear_device_auth_state() -> None:
    _device_auth_state_file().unlink(missing_ok=True)


def _device_auth_log_text() -> str:
    path = _device_auth_log_file()
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def codex_device_auth_status() -> dict[str, str | bool | int | None]:
    state = _device_auth_state()
    pid = int(state.get("pid") or 0) if str(state.get("pid") or "").isdigit() else None
    active = bool(pid and _pid_alive(pid))
    detail = _device_auth_log_text()
    if not active and state:
        _clear_device_auth_state()
    return {
        "active": active,
        "pid": pid,
        "detail": detail,
    }


def codex_auth_status() -> dict[str, str | bool]:
    payload = _load_auth_payload()
    tokens = payload.get("tokens") or {}
    access_exp = _jwt_expiry_epoch(tokens.get("access_token"))
    refresh_token = str(tokens.get("refresh_token") or "").strip()
    auth_mode = str(payload.get("auth_mode") or "").strip()
    now = int(time.time())
    logged_in = bool(refresh_token or (access_exp and access_exp > now))

    if logged_in:
        mode_text = "ChatGPT" if auth_mode == "chatgpt" else "Codex"
        detail = f"Logged in using {mode_text}"
    else:
        device = codex_device_auth_status()
        detail = "Not logged in"
        if device["active"] and device["detail"]:
            detail = str(device["detail"])

    return {
        "available": True,
        "logged_in": logged_in,
        "detail": detail,
    }


def start_codex_device_auth() -> dict[str, str | bool]:
    status = codex_auth_status()
    if status["logged_in"]:
        return {
            "ok": True,
            "started": False,
            "message": str(status["detail"]),
        }

    device = codex_device_auth_status()
    if device["active"]:
        return {
            "ok": True,
            "started": False,
            "message": str(device["detail"] or "Device login already in progress."),
        }

    log_file = _device_auth_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("", encoding="utf-8")
    with log_file.open("a", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [resolve_codex_binary(), "login", "--device-auth"],
            cwd=str(agent_repo_root()),
            env=codex_auth_env(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    _write_device_auth_state({"pid": proc.pid, "started_at": time.time()})

    deadline = time.time() + 8.0
    text = ""
    while time.time() < deadline:
        text = _device_auth_log_text()
        if "http" in text.lower() or "code" in text.lower() or text:
            break
        time.sleep(0.2)

    return {
        "ok": True,
        "started": True,
        "message": text or "Device login started. Use /auth-status for the latest login link.",
    }


def finalize_codex_device_auth() -> dict[str, str | bool]:
    repair_codex_auth_permissions()
    status = codex_auth_status()
    if status["logged_in"]:
        device = codex_device_auth_status()
        pid = device.get("pid")
        if isinstance(pid, int) and pid > 0 and _pid_alive(pid):
            try:
                os.killpg(pid, signal.SIGTERM)
            except Exception:
                pass
        _clear_device_auth_state()
    return status


def codex_auth_help_text(*, interactive_login_supported: bool) -> str:
    if interactive_login_supported:
        return "Codex is not authenticated for this Sheriff repo.\nSend /auth-login here to start browser sign-in."
    return "Codex is not authenticated for this Sheriff repo.\nSend /auth-login here to start browser sign-in."


def is_codex_auth_error(err: str) -> bool:
    norm = (err or "").lower()
    needles = (
        "401 unauthorized",
        "missing bearer or basic authentication",
        "not logged in",
        "unauthorized",
    )
    return any(needle in norm for needle in needles)
