from __future__ import annotations

import os
from pathlib import Path


def base_root() -> Path:
    root = os.environ.get("SHERIFFCLAW_ROOT")
    if root:
        return Path(root).expanduser()
    return Path.home() / ".sheriffclaw"


def gw_root() -> Path:
    p = base_root() / "gw"
    p.mkdir(parents=True, exist_ok=True)
    return p


def llm_root() -> Path:
    p = base_root() / "llm"
    p.mkdir(parents=True, exist_ok=True)
    return p
