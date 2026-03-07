from __future__ import annotations

import argparse

from services.sheriff_ctl.system import cmd_debug
from shared.codex_debug import load_config


def test_cmd_debug_codex_sets_chat_scenario(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    cmd_debug(argparse.Namespace(debug_args=["codex", "timeout"]))
    assert load_config()["chat"] == "timeout"
