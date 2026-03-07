from __future__ import annotations

from shared import paths


def test_agent_root_does_not_copy_seed_session_transcripts(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    src = tmp_path / "source" / "agents" / "codex" / "conversations" / "sessions" / "s1"
    src.mkdir(parents=True, exist_ok=True)
    (src / "100_user_agent.tmd").write_text("stale", encoding="utf-8")

    got = paths.agent_root()
    assert not (got / "conversations" / "sessions" / "s1" / "100_user_agent.tmd").exists()
    assert (got / "conversations" / "sessions").exists()
