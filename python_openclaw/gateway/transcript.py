from __future__ import annotations

import json
from pathlib import Path


class TranscriptStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def append(self, session_key: str, event: dict) -> None:
        path = self.base_dir / f"{session_key.replace(':', '_')}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
