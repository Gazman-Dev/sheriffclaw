import pytest
from datetime import datetime, timedelta, timezone

from shared.memory.store import TopicStore
from shared.memory.types import Topic, TopicTime
from shared.memory.retrieval import retrieve_topics, sync_semantic_index
from shared.memory.embedding import DeterministicHashEmbeddingProvider
from shared.memory.semantic_index import HnswlibSemanticIndex
from shared.memory.runtime import sleep


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_topic_decay_over_time(tmp_path):
    store = TopicStore(tmp_path / "topics.json")

    # Create topic 3 days ago with high utility
    old_time = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    t = Topic(
        schema_version=1,
        topic_id="decay-topic",
        name="Decay Target",
        one_liner="should decay",
        aliases=["decay"],
        time=TopicTime(first_seen_at=old_time, last_seen_at=old_time, notable_events=[]),
        stats={"utility_score": 10.0, "touch_count": 5}
    )
    store.create(t)

    # Trigger decay
    store.apply_decay(_now())

    updated = store.get("decay-topic")

    # 3 days = 10.0 * 0.98 * 0.98 * 0.98 ~ 9.41
    assert updated["stats"]["utility_score"] < 10.0
    assert updated["stats"]["utility_score"] > 9.0


def test_graph_linkage_and_expansion(tmp_path):
    store = TopicStore(tmp_path / "topics.json")
    embedder = DeterministicHashEmbeddingProvider(dim=64)
    index = HnswlibSemanticIndex(tmp_path / "semantic", dim=embedder.dim)
    index.load()

    # Topic A (Target of explicit search)
    store.create(Topic(
        schema_version=1, topic_id="A", name="Front End", one_liner="react components",
        aliases=["react"], time=TopicTime(first_seen_at=_now(), last_seen_at=_now())
    ))

    # Topic B (Unrelated text, but linked to A via graph)
    store.create(Topic(
        schema_version=1, topic_id="B", name="Secret Backend", one_liner="hidden database logic",
        aliases=["hidden"], time=TopicTime(first_seen_at=_now(), last_seen_at=_now())
    ))

    # Link A -> B
    store.link_topics("A", "B", "DEPENDS_ON", 1.0, _now())
    sync_semantic_index(store, embedder, index)

    # Deep search on A -> should pull in B through graph expansion
    # We trigger deep search using a trigger phrase "remember"
    res = retrieve_topics(
        query="remember react components",
        now_iso=_now(),
        wake_packet=None,
        topic_store=store,
        embedding_provider=embedder,
        semantic_index=index
    )

    assert res.deep_used is True
    retrieved_ids = [t["topic_id"] for t in res.topics]

    assert "A" in retrieved_ids
    assert "B" in retrieved_ids # Pulled in via 1-hop graph expansion


def test_sleep_co_activation_does_not_auto_link_in_chunk_a(tmp_path):
    store = TopicStore(tmp_path / "topics.json")
    embedder = DeterministicHashEmbeddingProvider(dim=64)
    index = HnswlibSemanticIndex(tmp_path / "semantic", dim=embedder.dim)
    index.load()

    # Create two topics with recognizable aliases
    store.create(Topic(
        schema_version=1, topic_id="srv", name="Server", one_liner="api server",
        aliases=["server"], time=TopicTime(first_seen_at=_now(), last_seen_at=_now())
    ))
    store.create(Topic(
        schema_version=1, topic_id="db", name="Database", one_liner="sql database",
        aliases=["database"], time=TopicTime(first_seen_at=_now(), last_seen_at=_now())
    ))
    sync_semantic_index(store, embedder, index)

    # Both mentioned heavily in the same compacted block
    conv = [
        {"role": "user", "content": "the server connects to the database"},
        {"role": "user", "content": "server needs more memory, database needs disk"},
    ]

    sleep(conv, _now(), store, keep_tail_turns=0, embedding_provider=embedder, semantic_index=index)

    # Chunk A scope: no automatic co-activation linking yet
    adj = store.get_adjacent_topics("srv")
    assert "db" not in adj