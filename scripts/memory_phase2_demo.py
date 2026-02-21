from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.memory.embedding import DeterministicHashEmbeddingProvider
from shared.memory.retrieval import retrieve_topics, sync_semantic_index
from shared.memory.semantic_index import HnswlibSemanticIndex
from shared.memory.store import TopicStore
from shared.memory.types import Topic, TopicTime


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        store = TopicStore(Path(td) / "topics.json")

        store.create(
            Topic(
                schema_version=1,
                topic_id="topic-sem",
                name="Concert Plan",
                one_liner="concert agenda and stage plan",
                aliases=["music ops"],
                time=TopicTime(first_seen_at="2026-01-01T00:00:00Z", last_seen_at="2026-01-01T00:00:00Z", notable_events=[]),
            )
        )
        store.create(
            Topic(
                schema_version=1,
                topic_id="topic-before",
                name="Party Before Sleep",
                one_liner="party guest list and snacks",
                aliases=["party"],
                time=TopicTime(first_seen_at="2026-01-01T00:00:00Z", last_seen_at="2026-01-01T10:00:00Z", notable_events=[]),
            )
        )
        store.create(
            Topic(
                schema_version=1,
                topic_id="topic-after",
                name="Party After Sleep",
                one_liner="party guest list and snacks",
                aliases=["party"],
                time=TopicTime(first_seen_at="2026-01-03T00:00:00Z", last_seen_at="2026-01-03T10:00:00Z", notable_events=[]),
            )
        )

        embedder = DeterministicHashEmbeddingProvider(dim=64)
        index = HnswlibSemanticIndex(Path(td) / "semantic", dim=embedder.dim)
        index.load()
        sync_semantic_index(store, embedder, index)
        index.save()

        alias_only = store.search_by_alias("concert stage plan", k=5)
        sem_res = retrieve_topics(
            query="concert stage plan",
            now_iso=now_iso(),
            wake_packet=None,
            topic_store=store,
            embedding_provider=embedder,
            semantic_index=index,
        )

        print("ALIAS_HITS", len(alias_only))
        print("SEMANTIC_HITS", len(sem_res.topics))
        print("SEMANTIC_CONTAINS_TOPIC_SEM", any(t.get("topic_id") == "topic-sem" for t in sem_res.topics))
        if sem_res.topics:
            print("SEMANTIC_TOP", sem_res.topics[0]["topic_id"])

        wake_packet = {
            "schema_version": 1,
            "slept_at": "2026-01-02T00:00:00Z",
            "conversation_tail": [],
            "active_subject_hints": [],
            "top_topic_ids": [],
            "recent_skill_refs": [],
            "in_progress": {"status": "idle", "resume_hint": "", "topic_id": ""},
        }
        before_sleep_res = retrieve_topics(
            query="before sleep party",
            now_iso="2026-01-04T00:00:00Z",
            wake_packet=wake_packet,
            topic_store=store,
            embedding_provider=embedder,
            semantic_index=index,
        )
        print("BEFORE_SLEEP_TOP", before_sleep_res.topics[0]["topic_id"] if before_sleep_res.topics else "none")


if __name__ == "__main__":
    main()
