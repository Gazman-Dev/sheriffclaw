from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class TranscriptStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def append(self, session_key: str, event: dict) -> None:
        path = self.base_dir / f"{session_key.replace(':', '_')}.md"
        block_type = event.get("type", "event").replace("_", " ").title()
        ts = datetime.now(timezone.utc).isoformat()
        content = event.get("content")
        if content is None:
            content = json.dumps(event, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"## {block_type} [{ts}]\n\n{content}\n\n")
