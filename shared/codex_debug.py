from __future__ import annotations

import json
from pathlib import Path

from shared.paths import gw_root

DEFAULT_CONFIG = {
    "chat": "success",
    "login_status": "ok",
}


def config_path() -> Path:
    path = gw_root() / "state" / "debug" / "codex_debug.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_config() -> dict[str, str]:
    path = config_path()
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_CONFIG)
    return {
        "chat": str(raw.get("chat") or DEFAULT_CONFIG["chat"]),
        "login_status": str(raw.get("login_status") or DEFAULT_CONFIG["login_status"]),
    }


def save_config(config: dict[str, str]) -> dict[str, str]:
    merged = {
        "chat": str(config.get("chat") or DEFAULT_CONFIG["chat"]),
        "login_status": str(config.get("login_status") or DEFAULT_CONFIG["login_status"]),
    }
    config_path().write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def reset_config() -> dict[str, str]:
    return save_config(dict(DEFAULT_CONFIG))
