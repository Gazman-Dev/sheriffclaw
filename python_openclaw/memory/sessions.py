from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class SessionConfig:
    token_limit: int = 40000


class SessionManager:
    def __init__(self, root: Path, config: SessionConfig | None = None):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = config or SessionConfig()

    def append(self, session_key: str, event: dict) -> None:
        path = self._session_path(session_key)
        heading = _heading_for_event(event)
        body = event.get("content") or json.dumps(event, ensure_ascii=False)
        timestamp = datetime.now(timezone.utc).isoformat()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"## {heading} [{timestamp}]\n\n{body}\n\n")

    def read(self, session_key: str) -> list[dict]:
        path = self._session_path(session_key)
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        return _markdown_to_messages(text)

    async def maybe_compact(self, session_key: str, summary_model: Any) -> bool:
        events = self.read(session_key)
        token_estimate = sum(_estimate_tokens(e) for e in events)
        if token_estimate <= self.config.token_limit:
            return False

        summary = summary_model(events)
        if inspect.isawaitable(summary):
            summary = await summary

        path = self._session_path(session_key)
        tail_events = events[-8:]
        compacted = [
            {"role": "system", "content": f"Summary of previous conversation: {summary}"},
            *tail_events,
        ]
        path.write_text(_messages_to_markdown(compacted), encoding="utf-8")
        return True

    def _session_path(self, session_key: str) -> Path:
        normalized = session_key.replace(":", "_").replace("/", "_")
        return self.root / f"{normalized}.md"


def _estimate_tokens(event: dict) -> int:
    content = json.dumps(event, ensure_ascii=False)
    return max(1, len(content) // 4)


def _heading_for_event(event: dict) -> str:
    role = event.get("role") or event.get("type") or "event"
    role = str(role).lower()
    mapping = {
        "user": "User",
        "assistant": "Assistant",
        "tool": "Tool Output",
        "tool.result": "Tool Output",
        "tool.call": "Tool Call",
        "system": "System",
    }
    return mapping.get(role, role.replace("_", " ").title())


def _markdown_to_messages(text: str) -> list[dict]:
    blocks = [part.strip() for part in text.split("\n## ") if part.strip()]
    parsed: list[dict] = []
    for index, block in enumerate(blocks):
        if index == 0 and block.startswith("## "):
            block = block[3:]
        lines = block.splitlines()
        if not lines:
            continue
        heading = lines[0].split("[", 1)[0].strip().lower()
        content = "\n".join(lines[1:]).strip()
        if heading.startswith("user"):
            parsed.append({"role": "user", "content": content})
        elif heading.startswith("assistant"):
            parsed.append({"role": "assistant", "content": content})
        elif heading.startswith("system"):
            parsed.append({"role": "system", "content": content})
        else:
            parsed.append({"role": "tool", "content": content})
    return parsed


def _messages_to_markdown(messages: list[dict]) -> str:
    output: list[str] = []
    for msg in messages:
        output.append(f"## {_heading_for_event(msg)}")
        output.append("")
        output.append(msg.get("content", ""))
        output.append("")
    return "\n".join(output).rstrip() + "\n"
