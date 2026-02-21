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

        store.create(Topic(
            schema_version=1,
            topic_id="A",
            name="React Frontend",
            one_liner="react components and ui",
            aliases=["react"],
            time=TopicTime(first_seen_at=now_iso(), last_seen_at=now_iso(), notable_events=[]),
        ))
        store.create(Topic(
            schema_version=1,
            topic_id="B",
            name="Hidden Backend",
            one_liner="database joins and backend internals",
            aliases=["backend"],
            time=TopicTime(first_seen_at=now_iso(), last_seen_at=now_iso(), notable_events=[]),
        ))

        # graph link
        store.link_topics("A", "B", "RELATES_TO", 1.0, now_iso(), mode="add")

        embedder = DeterministicHashEmbeddingProvider(dim=64)
        index = HnswlibSemanticIndex(Path(td) / "semantic", dim=embedder.dim)
        index.load()
        sync_semantic_index(store, embedder, index)

        res = retrieve_topics(
            query="remember react components",
            now_iso=now_iso(),
            wake_packet=None,
            topic_store=store,
            embedding_provider=embedder,
            semantic_index=index,
        )

        ids = [t.get("topic_id") for t in res.topics]
        print("DEEP_USED", res.deep_used)
        print("RETRIEVED_IDS", ",".join(ids))
        print("GRAPH_EXPANSION_HELPED", "B" in ids)


if __name__ == "__main__":
    main()
