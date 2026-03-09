from __future__ import annotations

import json
import re
from pathlib import Path

from shared.paths import gw_root


def load_target_versions(repo_root: Path) -> dict[str, str]:
    fp = repo_root / "versions.json"
    if not fp.exists():
        return {"agent": "0.0.0", "sheriff": "0.0.0", "secrets": "0.0.0"}
    try:
        obj = json.loads(fp.read_text(encoding="utf-8"))
        return {
            "agent": str(obj.get("agent", "0.0.0")),
            "sheriff": str(obj.get("sheriff", "0.0.0")),
            "secrets": str(obj.get("secrets", "0.0.0")),
        }
    except Exception:
        return {"agent": "0.0.0", "sheriff": "0.0.0", "secrets": "0.0.0"}


def load_applied_versions() -> dict[str, str]:
    fp = gw_root() / "state" / "update_versions.json"
    if not fp.exists():
        return {"agent": "0.0.0", "sheriff": "0.0.0", "secrets": "0.0.0"}
    try:
        obj = json.loads(fp.read_text(encoding="utf-8"))
        return {
            "agent": str(obj.get("agent", "0.0.0")),
            "sheriff": str(obj.get("sheriff", "0.0.0")),
            "secrets": str(obj.get("secrets", "0.0.0")),
        }
    except Exception:
        return {"agent": "0.0.0", "sheriff": "0.0.0", "secrets": "0.0.0"}


def save_applied_versions(versions: dict[str, str]) -> None:
    fp = gw_root() / "state" / "update_versions.json"
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(versions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v or "")
    if not nums:
        return (0,)
    return tuple(int(n) for n in nums)


def is_increased(new_v: str, old_v: str) -> bool:
    return _parse_version(new_v) > _parse_version(old_v)


def diff_versions(target: dict[str, str], applied: dict[str, str]) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for key in ("agent", "sheriff", "secrets"):
        prev = applied.get(key, "0.0.0")
        nxt = target.get(key, "0.0.0")
        out[key] = {
            "from": prev,
            "to": nxt,
            "increased": is_increased(nxt, prev),
        }
    return out
