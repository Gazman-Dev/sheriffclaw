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
    (src / "config.toml").write_text("model = \"gpt-5\"\n", encoding="utf-8")
    (src / "AGENTS.md").write_text("template", encoding="utf-8")

    got = paths.agent_root()
    assert (got / "config.toml").exists()
    assert (got / "AGENTS.md").exists()
    assert 'trust_level = "trusted"' in (got / "config.toml").read_text(encoding="utf-8")


def test_agent_root_does_not_overwrite_existing_files(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    dst = tmp_path / "agents" / "codex"
    (dst / ".codex").mkdir(parents=True, exist_ok=True)
    (dst / "config.toml").write_text("original", encoding="utf-8")

    src = tmp_path / "source" / "agents" / "codex"
    src.mkdir(parents=True, exist_ok=True)
    (src / "config.toml").write_text("template", encoding="utf-8")

    got = paths.agent_root()
    assert (got / "config.toml").read_text(encoding="utf-8").startswith("original")


def test_agent_root_migrates_legacy_dot_codex_config(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    dst = tmp_path / "agents" / "codex" / ".codex"
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "config.toml").write_text(
        'model = "gpt-5"\nconfig_file = ".codex/roles/subagent-high.toml"\n',
        encoding="utf-8",
    )

    got = paths.agent_root()
    assert (got / "config.toml").exists()
    assert not (got / ".codex" / "config.toml").exists()
    assert 'config_file = "roles/subagent-high.toml"' in (got / "config.toml").read_text(encoding="utf-8")


def test_agent_root_backs_up_conflicting_legacy_dot_codex_config(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    dst = tmp_path / "agents" / "codex"
    (dst / ".codex").mkdir(parents=True, exist_ok=True)
    (dst / "config.toml").write_text("model = \"gpt-5\"\n", encoding="utf-8")
    (dst / ".codex" / "config.toml").write_text("model = \"gpt-4\"\n", encoding="utf-8")

    got = paths.agent_root()
    assert (got / "config.toml").read_text(encoding="utf-8").startswith('model = "gpt-5"')
    assert not (got / ".codex" / "config.toml").exists()
    assert (got / ".codex" / "config.toml.legacy").exists()


def test_agent_root_rewrites_legacy_role_refs_in_existing_global_config(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    dst = tmp_path / "agents" / "codex"
    (dst / ".codex").mkdir(parents=True, exist_ok=True)
    (dst / "config.toml").write_text(
        'model = "gpt-5"\nconfig_file = ".codex/roles/subagent-medium.toml"\n',
        encoding="utf-8",
    )

    got = paths.agent_root()
    assert 'config_file = "roles/subagent-medium.toml"' in (got / "config.toml").read_text(encoding="utf-8")
