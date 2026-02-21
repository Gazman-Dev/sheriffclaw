from datetime import datetime, timezone
from pathlib import Path

from shared.memory.embedding import DeterministicHashEmbeddingProvider
from shared.memory.phase4_runtime import MockCodexAdapter, Phase4RuntimeConfig, RuntimeStores, run_turn
from shared.memory.retrieval import sync_semantic_index
from shared.memory.semantic_index import HnswlibSemanticIndex
from shared.memory.store import TopicStore
from shared.memory.types import Topic, TopicTime


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _skill_runner(skill_id: str, args: dict) -> dict:
    return {"skill_id": skill_id, "ok": True, "args": args}


def test_phase4_tool_loop_repo_write(tmp_path):
    store = TopicStore(tmp_path / "topics.json")
    store.create(
        Topic(
            schema_version=1,
            topic_id="topic-1",
            name="Party",
            one_liner="party planning and budget",
            aliases=["party"],
            time=TopicTime(first_seen_at=_now(), last_seen_at=_now(), notable_events=[]),
        )
    )

    embedder = DeterministicHashEmbeddingProvider(dim=64)
    index = HnswlibSemanticIndex(tmp_path / "semantic", dim=embedder.dim)
    index.load()
    sync_semantic_index(store, embedder, index)

    writes = {}

    def repo_write(args: dict) -> dict:
        writes[args["path"]] = args["content"]
        return {"status": "ok"}

    stores = RuntimeStores(
        topic_store=store,
        embedding_provider=embedder,
        semantic_index=index,
        wake_packet=None,
        skills_root=Path("skills"),
        skill_runner=_skill_runner,
        repo_tools={"repo.write_file": repo_write},
    )

    out = run_turn(
        conversation_buffer=[],
        user_msg="please edit repo file",
        now=_now(),
        stores=stores,
        config=Phase4RuntimeConfig(token_sleep_threshold=10000),
        model_adapter=MockCodexAdapter(),
    )

    assert "README.md" in writes
    assert out["assistant_msg"] == "Done. Tool output received and applied."
    assert any(e.get("type") == "tool_call" and e.get("name") == "repo.write_file" for e in out["logs"]["events"])


def test_phase4_sleep_wake_integration(tmp_path):
    store = TopicStore(tmp_path / "topics.json")
    store.create(
        Topic(
            schema_version=1,
            topic_id="topic-2",
            name="Legacy Topic",
            one_liner="legacy project decisions",
            aliases=["legacy"],
            time=TopicTime(first_seen_at=_now(), last_seen_at=_now(), notable_events=[]),
        )
    )
    embedder = DeterministicHashEmbeddingProvider(dim=64)
    index = HnswlibSemanticIndex(tmp_path / "semantic", dim=embedder.dim)
    index.load()
    sync_semantic_index(store, embedder, index)

    long_buffer = [{"role": "user", "content": "x" * 1000} for _ in range(80)]

    stores = RuntimeStores(
        topic_store=store,
        embedding_provider=embedder,
        semantic_index=index,
        wake_packet=None,
        skills_root=Path("skills"),
        skill_runner=_skill_runner,
        repo_tools={},
    )

    out = run_turn(
        conversation_buffer=long_buffer,
        user_msg="remember legacy",
        now=_now(),
        stores=stores,
        config=Phase4RuntimeConfig(token_sleep_threshold=500),
        model_adapter=MockCodexAdapter(),
    )

    assert out["maybe_wake_packet"] is not None
    assert any(e.get("type") == "sleep" for e in out["logs"]["events"])
    assert any(e.get("type") == "wake" for e in out["logs"]["events"])
