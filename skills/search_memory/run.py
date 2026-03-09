#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# Add repo root to sys.path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def score_text(query: str, text: str) -> float:
    toks = [t for t in query.lower().split() if t]
    if not toks:
        return 0.0
    low = text.lower()
    hits = sum(1 for t in toks if t in low)
    return hits / len(toks)


def main():
    query = " ".join(sys.argv[1:]).strip()
    if not query:
        print("Usage: python run.py <recall_query>")
        sys.exit(1)

    base = Path(os.environ.get("SHERIFFCLAW_ROOT", Path.home() / ".sheriffclaw")).resolve()
    workspace = base / "agent_workspace"
    if not workspace.exists():
        print("No past memories found matching that query.")
        return

    rows = []
    for p in workspace.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".md", ".txt", ".jsonl", ".json"}:
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        s = score_text(query, content)
        if s > 0:
            rows.append((s, p, content))

    rows.sort(key=lambda x: x[0], reverse=True)
    if not rows:
        print("No past memories found matching that query.")
        return

    print("--- Past Conversation Recall ---")
    for score, p, content in rows[:5]:
        print(f"[Similarity: {score:.2f}]")
        print(str(p))
        print(content[:1200].strip())
        print("-" * 30)


if __name__ == "__main__":
    main()
