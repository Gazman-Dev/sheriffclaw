from pathlib import Path

from shared import paths


def test_agent_root_under_sheriffclaw_root(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    got = paths.agent_root()
    assert got == tmp_path / "agents" / "codex"
    assert (got / ".codex").exists()
    assert (got / "conversations" / "sessions").exists()
    assert (got / "skill").exists()
    assert (got / "tmp").exists()


def test_agent_root_seeds_from_installer_source(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    src = tmp_path / "source" / "agents" / "codex"
    (src / ".codex").mkdir(parents=True, exist_ok=True)
    (src / ".codex" / "config.toml").write_text("model = \"gpt-5\"\n", encoding="utf-8")
    (src / "AGENTS.md").write_text("template", encoding="utf-8")

    got = paths.agent_root()
    assert (got / ".codex" / "config.toml").exists()
    assert (got / "AGENTS.md").exists()


def test_agent_root_does_not_overwrite_existing_files(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    dst = tmp_path / "agents" / "codex"
    (dst / ".codex").mkdir(parents=True, exist_ok=True)
    (dst / ".codex" / "config.toml").write_text("original", encoding="utf-8")

    src = tmp_path / "source" / "agents" / "codex"
    (src / ".codex").mkdir(parents=True, exist_ok=True)
    (src / ".codex" / "config.toml").write_text("template", encoding="utf-8")

    got = paths.agent_root()
    assert (got / ".codex" / "config.toml").read_text(encoding="utf-8") == "original"
