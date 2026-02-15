from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from python_openclaw.common.ndjson import append_jsonl, iter_jsonl


@dataclass
class SessionConfig:
    token_limit: int = 40000


class SessionManager:
    def __init__(self, root: Path, config: SessionConfig | None = None):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = config or SessionConfig()

    def append(self, session_key: str, event: dict) -> None:
        append_jsonl(self._session_path(session_key), event)

    def read(self, session_key: str) -> list[dict]:
        path = self._session_path(session_key)
        if not path.exists():
            return []
        return list(iter_jsonl(path))

    def maybe_compact(self, session_key: str, summary_model: callable) -> bool:
        events = self.read(session_key)
        token_estimate = sum(_estimate_tokens(e) for e in events)
        if token_estimate <= self.config.token_limit:
            return False
        summary = summary_model(events)
        keep = [e for e in events if e.get("role") == "system"]
        compacted = keep + [{"role": "system", "content": f"Conversation summary: {summary}"}] + events[-8:]
        path = self._session_path(session_key)
        path.write_text("\n".join(json.dumps(e) for e in compacted) + "\n", encoding="utf-8")
        return True

    def _session_path(self, session_key: str) -> Path:
        normalized = session_key.replace(":", "_").replace("/", "_")
        return self.root / f"{normalized}.jsonl"


def _estimate_tokens(event: dict) -> int:
    content = json.dumps(event, ensure_ascii=False)
    return max(1, len(content) // 4)
