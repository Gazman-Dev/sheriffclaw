from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from shared.codex_debug import load_config


def _script() -> Path:
    return Path(__file__).resolve().parents[1] / "debug" / "codex" / "codex_debug.py"


def test_codex_debug_login_status_reflects_config(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    subprocess.run([sys.executable, str(_script()), "login-missing"], check=True)
    result = subprocess.run([sys.executable, str(_script()), "login", "status"], check=False)
    assert result.returncode == 1

    subprocess.run([sys.executable, str(_script()), "login-ok"], check=True)
    result = subprocess.run([sys.executable, str(_script()), "login", "status"], check=False)
    assert result.returncode == 0


def test_codex_debug_scenario_commands_persist_config(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    subprocess.run([sys.executable, str(_script()), "timeout"], check=True)
    assert load_config()["chat"] == "timeout"

    result = subprocess.run([sys.executable, str(_script()), "show"], check=True, capture_output=True, text=True)
    shown = json.loads(result.stdout)
    assert shown["chat"] == "timeout"

    subprocess.run([sys.executable, str(_script()), "clear"], check=True)
    assert load_config() == {"chat": "success", "login_status": "ok"}
