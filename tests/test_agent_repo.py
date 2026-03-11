from __future__ import annotations

import json
import subprocess
import sys

from shared import agent_repo
from shared import paths


def test_agent_repo_root_creates_required_directories(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    root = paths.agent_repo_root()

    assert root == tmp_path / "agent_repo"
    for rel in ("memory", "tasks", "sessions", "skills", "system", "logs"):
        assert (root / rel).exists()


def test_ensure_layout_seeds_default_files(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    root = agent_repo.ensure_layout()

    assert root == tmp_path / "agent_repo"
    assert (root / "memory" / "user_profile.md").exists()
    assert (root / "memory" / "summaries").exists()
    assert (root / ".codex" / "config.toml").exists()
    assert "Preserve raw user meaning" in (root / "AGENTS.md").read_text(encoding="utf-8")
    assert (root / "skills" / "task-manager" / "SKILL.md").exists()
    assert (root / "skills" / "memory-manager" / "SKILL.md").exists()
    assert (root / "skills" / "cron-job" / "SKILL.md").exists()
    assert (root / "skills" / "sheriff" / "SKILL.md").exists()
    assert (root / "skills" / "sheriff" / "scripts" / "install_wrapper.py").exists()
    assert json.loads((root / "sessions" / "sessions.json").read_text(encoding="utf-8"))["version"] == 1
    assert json.loads((root / "tasks" / "task_index.json").read_text(encoding="utf-8"))["version"] == 1
    assert json.loads((root / "system" / "maintenance_state.json").read_text(encoding="utf-8"))["heartbeat"]["status"] == "idle"


def test_ensure_session_artifacts_creates_session_and_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    artifacts = agent_repo.ensure_session_artifacts("private_main")

    session_payload = json.loads(artifacts["session"].read_text(encoding="utf-8"))
    assert artifacts["session"] == tmp_path / "agent_repo" / "sessions" / "private_main.json"
    assert artifacts["summary"] == tmp_path / "agent_repo" / "memory" / "summaries" / "private_main.md"
    assert session_payload["session_key"] == "private_main"
    assert session_payload["thread_id"] is None
    assert artifacts["summary"].read_text(encoding="utf-8").startswith("# Session Summary: private_main")


def test_sheriff_wrapper_installer_creates_git_shims(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    root = agent_repo.ensure_layout()
    script = root / "skills" / "sheriff" / "scripts" / "install_wrapper.py"

    subprocess.run(
        [sys.executable, str(script), "--command", "git", "--secrets", "GIT_TOKEN"],
        check=True,
        cwd=str(root),
        capture_output=True,
        text=True,
    )

    unix_wrapper = root / "skills" / "sheriff" / "bin" / "git"
    cmd_wrapper = root / "skills" / "sheriff" / "bin" / "git.cmd"
    assert unix_wrapper.exists()
    assert cmd_wrapper.exists()
    assert 'exec sheriff git GIT_TOKEN "$@"' in unix_wrapper.read_text(encoding="utf-8")
    assert "sheriff git GIT_TOKEN %*" in cmd_wrapper.read_text(encoding="utf-8")
