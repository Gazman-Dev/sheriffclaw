from __future__ import annotations

from shared import paths


def test_agent_repo_root_does_not_create_legacy_conversation_tree(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    got = paths.agent_repo_root()

    assert not (got / "conversations" / "sessions").exists()
    assert (got / "sessions").exists()
