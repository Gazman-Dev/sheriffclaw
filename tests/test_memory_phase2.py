from datetime import datetime, timezone

from shared.memory.embedding import DeterministicHashEmbeddingProvider
from shared.memory.retrieval import retrieve_topics, sync_semantic_index
from shared.memory.semantic_index import HnswlibSemanticIndex
from shared.memory.store import TopicStore
from shared.memory.types import Topic, TopicTime


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_alias_miss_semantic_hit(tmp_path):
    store = TopicStore(tmp_path / "topics.json")
    topic = Topic(
        schema_version=1,
        topic_id="topic-1",
        name="Concert Plan",
        one_liner="concert agenda and stage plan",
        aliases=["music project"],
        time=TopicTime(first_seen_at=_now(), last_seen_at=_now(), notable_events=[]),
    )
    store.create(topic)

    embedder = DeterministicHashEmbeddingProvider(dim=64)
    index = HnswlibSemanticIndex(tmp_path / "semantic", dim=embedder.dim)
    index.load()
    sync_semantic_index(store, embedder, index)
    index.save()

    result = retrieve_topics(
        query="concert agenda",
        now_iso=_now(),
        wake_packet=None,
        topic_store=store,
        embedding_provider=embedder,
        semantic_index=index,
    )
    assert len(result.topics) >= 1
    assert result.topics[0]["topic_id"] == "topic-1"


def test_before_sleep_boost(tmp_path):
    store = TopicStore(tmp_path / "topics.json")

    older = Topic(
        schema_version=1,
        topic_id="topic-old",
        name="Party Before Sleep",
        one_liner="party guest list and agenda",
        aliases=["party"],
        time=TopicTime(first_seen_at="2026-01-01T00:00:00Z", last_seen_at="2026-01-01T10:00:00Z", notable_events=[]),
    )
    newer = Topic(
        schema_version=1,
        topic_id="topic-new",
        name="Party After Sleep",
        one_liner="party guest list and agenda",
        aliases=["party"],
        time=TopicTime(first_seen_at="2026-01-03T00:00:00Z", last_seen_at="2026-01-03T10:00:00Z", notable_events=[]),
    )
    store.create(older)
    store.create(newer)

    embedder = DeterministicHashEmbeddingProvider(dim=64)
    index = HnswlibSemanticIndex(tmp_path / "semantic", dim=embedder.dim)
    index.load()
    sync_semantic_index(store, embedder, index)

    wake_packet = {
        "schema_version": 1,
        "slept_at": "2026-01-02T00:00:00Z",
        "conversation_tail": [],
        "active_subject_hints": [],
        "top_topic_ids": [],
        "recent_skill_refs": [],
        "in_progress": {"status": "idle", "resume_hint": "", "topic_id": ""},
    }

    result = retrieve_topics(
        query="before sleep party",
        now_iso="2026-01-04T00:00:00Z",
        wake_packet=wake_packet,
        topic_store=store,
        embedding_provider=embedder,
        semantic_index=index,
    )

    assert result.deep_used is True
    assert result.topics[0]["topic_id"] == "topic-old"
