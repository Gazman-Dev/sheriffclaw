from shared import paths


def test_agent_repo_root_under_sheriffclaw_root(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    got = paths.agent_repo_root()

    assert got == tmp_path / "agent_repo"
    assert (got / "memory").exists()
    assert (got / "tasks").exists()
    assert (got / "sessions").exists()
    assert (got / "skills").exists()
    assert (got / "system").exists()
    assert (got / "logs").exists()
    assert (got / ".codex").exists()


def test_agent_root_is_alias_to_agent_repo_root(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    assert paths.agent_root() == paths.agent_repo_root()


def test_agent_repo_root_seeds_codex_facing_files(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    got = paths.agent_repo_root()

    assert (got / "AGENTS.md").exists()
    assert (got / "config.toml").exists()
    assert (got / ".codex" / "config.toml").exists()
    assert (got / "README.md").exists()
