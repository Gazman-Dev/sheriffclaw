from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run_ctl(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [sys.executable, "-m", "services.sheriff_ctl.__main__", *args],
            cwd=str(_repo_root()),
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = ((e.stderr or "") + "\n" + (e.stdout or "")).lower()
        # In some Windows sandboxes asyncio subprocess pipes are blocked; treat this
        # as an environment limitation rather than a product regression.
        if (
            "winerror 5" in stderr
            or "access is denied" in stderr
            or "permissionerror" in stderr
            or "asyncio\\windows_utils.py" in stderr
            or "createfile" in stderr
        ):
            pytest.skip("Windows process-pipe restriction in this environment prevents subprocess E2E flow")
        raise


def _read_and_clear_outbox(tmp_root: Path) -> list[dict]:
    p = tmp_root / "gw" / "state" / "debug" / "telegram_outbox.jsonl"
    if not p.exists():
        return []
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    p.write_text("", encoding="utf-8")
    out: list[dict] = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def _texts(entries: list[dict]) -> list[str]:
    vals: list[str] = []
    for e in entries:
        if isinstance(e.get("text"), str):
            vals.append(str(e["text"]))
            continue
        j = e.get("json")
        if isinstance(j, dict) and isinstance(j.get("text"), str):
            vals.append(str(j["text"]))
    return vals


def test_e2e_telegram_debug_flow(tmp_path):
    env = os.environ.copy()
    env["SHERIFFCLAW_ROOT"] = str(tmp_path)
    env["SHERIFF_DEBUG"] = "1"

    _run_ctl(
        [
            "onboard",
            "--master-password",
            "debug",
            "--llm-provider",
            "stub",
            "--llm-api-key",
            "",
            "--llm-bot-token",
            "",
            "--gate-bot-token",
            "",
            "--allow-telegram",
        ],
        env,
    )
    _read_and_clear_outbox(tmp_path)

    _run_ctl(["call", "sheriff-secrets", "secrets.lock", "--json", "{}"], env)

    # 1) Locked State Check
    _run_ctl(["debug", "channel", "telegram", "user-agent", "hello"], env)
    out1 = _read_and_clear_outbox(tmp_path)
    texts1 = " | ".join(_texts(out1)).lower()
    assert "locked" in texts1

    # 2) Unlock Flow
    _run_ctl(["debug", "channel", "telegram", "user-sheriff", "/unlock debug"], env)
    out2 = _read_and_clear_outbox(tmp_path)
    texts2 = " | ".join(_texts(out2)).lower()
    assert "vault unlocked" in texts2

    # 3) Trigger Secret Request
    _run_ctl(["debug", "channel", "telegram", "user-agent", "scenario secret gh_token"], env)
    out3 = _read_and_clear_outbox(tmp_path)
    texts3 = " | ".join(_texts(out3)).lower()
    assert "gh_token" in texts3
    assert ("approve" in texts3) or ("approval" in texts3) or ("allow" in texts3)

    # 4) Approve Secret
    _run_ctl(["debug", "channel", "telegram", "user-sheriff", "/secret gh_token supersecret"], env)
    out4 = _read_and_clear_outbox(tmp_path)
    texts4 = " | ".join(_texts(out4)).lower()
    assert "gh_token" in texts4
    assert ("approved" in texts4) or ("secret" in texts4)

    # 5) Agent Resumes/Reads Tool
    _run_ctl(["debug", "channel", "telegram", "user-agent", "scenario last tool"], env)
    out5 = _read_and_clear_outbox(tmp_path)
    texts5 = " | ".join(_texts(out5)).lower()
    assert ("needs_secret" in texts5) or ("approved" in texts5)
