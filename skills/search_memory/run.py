#!/usr/bin/env python3
import sys
from pathlib import Path

# Add repo root to sys.path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.memory.embedding import LocalSemanticEmbeddingProvider
from shared.memory.semantic_index import HnswlibSemanticIndex

def main():
    query = " ".join(sys.argv[1:]).strip()
    if not query:
        print("Usage: python run.py <recall_query>")
        sys.exit(1)

    memory_dir = ROOT / ".memory"

    try:
        provider = LocalSemanticEmbeddingProvider()
        index = HnswlibSemanticIndex(memory_dir / "semantic", name="conversations", dim=provider.dim)
        index.load()
    except Exception as e:
        print(f"Error loading conversation memory: {e}")
        sys.exit(1)

    query_vec = provider.embed(query)
    hits = index.search(query_vec, k=3)

    if not hits:
        print("No past memories found matching that query.")
        return

    print("--- Past Conversation Recall ---")
    for chunk_id, score in hits:
        print(f"[Similarity: {score:.2f}]")
        transcript_file = memory_dir / "transcripts" / f"{chunk_id}.txt"
        if transcript_file.exists():
            print(transcript_file.read_text(encoding="utf-8"))
            print("-" * 30)

if __name__ == "__main__":
    main()