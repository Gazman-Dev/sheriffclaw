# File: services/sheriff_ctl/utils.py

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import select

try:
    import termios  # type: ignore
    import tty  # type: ignore

    HAS_TERMIOS = True
except Exception:  # Windows / non-POSIX
    termios = None  # type: ignore
    tty = None  # type: ignore
    HAS_TERMIOS = False

from shared.oplog import get_op_logger
from shared.paths import gw_root, llm_root
from shared.proc_rpc import ProcClient

OPLOG = get_op_logger("ctl")


def _island_root(service: str) -> Path:
    return gw_root() if service.startswith("sheriff-") else llm_root()


def _pid_path(service: str) -> Path:
    return _island_root(service) / "run" / f"{service}.pid"


def _log_paths(service: str) -> tuple[Path, Path]:
    root = _island_root(service) / "logs"
    return root / f"{service}.out", root / f"{service}.err"


def _resolve_service_binary(service: str) -> str:
    venv_bin = Path(sys.executable).parent / service
    return str(venv_bin) if venv_bin.exists() else service


def _telegram_unlock_channel_path() -> Path:
    return gw_root() / "state" / "telegram_unlock_channel.json"


def _save_telegram_unlock_channel(*, token: str, user_id: str | None) -> None:
    p = _telegram_unlock_channel_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"token": token or "", "user_id": str(user_id or "")}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _clear_telegram_unlock_channel() -> None:
    _telegram_unlock_channel_path().unlink(missing_ok=True)


def _load_telegram_unlock_channel() -> dict:
    p = _telegram_unlock_channel_path()
    if not p.exists():
        return {}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        return {"token": str(obj.get("token", "")), "user_id": str(obj.get("user_id", ""))}
    except Exception:
        return {}


def _notify_sheriff_channel(text: str) -> bool:
    cfg = _load_telegram_unlock_channel()
    token = cfg.get("token", "")
    user_id = cfg.get("user_id", "")
    if not token or not user_id:
        return False
    try:
        import requests

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": int(user_id), "text": text, "disable_web_page_preview": True},
            timeout=15,
        )
        return True
    except Exception:
        return False


def _wait_extra_or_esc_until(deadline_ts: float) -> None:
    remaining = max(0.0, deadline_ts - time.time())
    if not sys.stdin.isatty():
        time.sleep(remaining)
        return

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while time.time() < deadline_ts:
            timeout = min(0.2, max(0.0, deadline_ts - time.time()))
            r, _, _ = select.select([fd], [], [], timeout)
            if not r:
                continue
            ch = os.read(fd, 1)
            if ch == b"\x1b":
                print("\n(wait cancelled)")
                return
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _is_onboarded() -> bool:
    state = gw_root() / "state"
    for name in ("secrets.db", "secrets.enc", "master.json"):
        if (state / name).exists():
            return True
    return False


async def _verify_master_password_async(mp: str) -> bool:
    gw = ProcClient("sheriff-gateway")
    _, res = await gw.request("gateway.verify_master_password", {"master_password": mp})
    return bool(res.get("result", {}).get("ok"))


def _verify_master_password(mp: str) -> bool:
    return asyncio.run(_verify_master_password_async(mp))


async def _gw_secrets_call(op: str, payload: dict | None = None, gw: ProcClient | None = None) -> dict:
    cli = gw or ProcClient("sheriff-gateway")
    _, res = await cli.request("gateway.secrets.call", {"op": op, "payload": payload or {}})
    outer = res.get("result", {})
    # gateway.secrets.call returns {ok, result, error}; unwrap for callers.
    if isinstance(outer, dict) and "result" in outer:
        if not outer.get("ok", True):
            return {"_error": outer.get("error")}
        inner = outer.get("result", {})
        return inner if isinstance(inner, dict) else {}
    return outer if isinstance(outer, dict) else {}
