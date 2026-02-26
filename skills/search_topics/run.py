#!/usr/bin/env python3
import sys
from pathlib import Path

# Add repo root to sys.path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.memory.embedding import LocalSemanticEmbeddingProvider
from shared.memory.semantic_index import HnswlibSemanticIndex
from shared.memory.store import TopicStore
from shared.memory.retrieval import render_topic_md

def main():
    query = " ".join(sys.argv[1:]).strip()
    if not query:
        print("Usage: python run.py <topic_query>")
        sys.exit(1)

    memory_dir = ROOT / ".memory"

    try:
        provider = LocalSemanticEmbeddingProvider()
        index = HnswlibSemanticIndex(memory_dir / "semantic", name="topics", dim=provider.dim)
        index.load()
        store = TopicStore(memory_dir / "topics.json")
    except Exception as e:
        print(f"Error loading topic memory: {e}")
        sys.exit(1)

    query_vec = provider.embed(query)
    hits = index.search(query_vec, k=5)

    if not hits:
        print("No topics or facts found.")
        return

    print("--- Topic Database Results ---")
    for tid, score in hits:
        topic = store.get(tid)
        if topic:
            print(f"[Score: {score:.2f}]")
            print(render_topic_md(topic))
            print("-" * 30)

if __name__ == "__main__":
    main()