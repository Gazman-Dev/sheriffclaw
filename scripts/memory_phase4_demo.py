from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.memory.embedding import DeterministicHashEmbeddingProvider
from shared.memory.phase4_runtime import MockCodexAdapter, Phase4RuntimeConfig, RuntimeStores, run_turn
from shared.memory.retrieval import sync_semantic_index
from shared.memory.semantic_index import HnswlibSemanticIndex
from shared.memory.store import TopicStore
from shared.memory.types import Topic, TopicTime


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def skill_runner(skill_id: str, args: dict) -> dict:
    return {"skill_id": skill_id, "ok": True, "args": args}


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        store = TopicStore(Path(td) / "topics.json")
        store.create(
            Topic(
                schema_version=1,
                topic_id="topic-old-party",
                name="Party Plan",
                one_liner="party plan and guest list",
                aliases=["party"],
                time=TopicTime(first_seen_at="2026-01-01T00:00:00Z", last_seen_at="2026-01-01T12:00:00Z", notable_events=[]),
            )
        )

        embedder = DeterministicHashEmbeddingProvider(dim=64)
        index = HnswlibSemanticIndex(Path(td) / "semantic", dim=embedder.dim)
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
            skills_root=ROOT / "skills",
            skill_runner=skill_runner,
            repo_tools={"repo.write_file": repo_write},
        )

        # 1) old topic retrieval
        out1 = run_turn(
            conversation_buffer=[],
            user_msg="remember the party",
            now=now_iso(),
            stores=stores,
            config=Phase4RuntimeConfig(token_sleep_threshold=10000),
            model_adapter=MockCodexAdapter(),
        )
        print("TOPIC_RETRIEVED", "topic-old-party" in out1["logs"].get("retrieved_topic_ids", []))

        # 2) tool call to edit file
        out2 = run_turn(
            conversation_buffer=out1["updated_buffer"],
            user_msg="please edit repo file",
            now=now_iso(),
            stores=stores,
            config=Phase4RuntimeConfig(token_sleep_threshold=10000),
            model_adapter=MockCodexAdapter(),
        )
        print("TOOL_CALLED_WRITE", any(e.get("name") == "repo.write_file" for e in out2["logs"].get("events", [])))

        # 3) sleep/wake on long buffer
        long_buffer = [{"role": "user", "content": "x" * 1000} for _ in range(80)]
        out3 = run_turn(
            conversation_buffer=long_buffer,
            user_msg="remember the party before sleep",
            now=now_iso(),
            stores=stores,
            config=Phase4RuntimeConfig(token_sleep_threshold=500),
            model_adapter=MockCodexAdapter(),
        )
        print("SLEEP_TRIGGERED", any(e.get("type") == "sleep" for e in out3["logs"].get("events", [])))
        print("WAKE_RESUMED", any(e.get("type") == "wake" for e in out3["logs"].get("events", [])))


if __name__ == "__main__":
    main()
