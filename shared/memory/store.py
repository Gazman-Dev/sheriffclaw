from __future__ import annotations

import json
import re
from pathlib import Path

from shared.memory.types import Topic, TopicTime


def normalize_alias(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", text.lower())).strip()


class TopicStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict]:
        if not self.db_path.exists():
            return []
        return json.loads(self.db_path.read_text(encoding="utf-8"))

    def _save(self, topics: list[dict]) -> None:
        self.db_path.write_text(json.dumps(topics, ensure_ascii=False, indent=2), encoding="utf-8")

    def create(self, topic: Topic) -> dict:
        topics = self._load()
        topics.append(topic.to_dict())
        self._save(topics)
        return topic.to_dict()

    def get(self, topic_id: str) -> dict | None:
        for topic in self._load():
            if topic.get("topic_id") == topic_id:
                return topic
        return None

    def update(self, topic_id: str, patch: dict) -> dict | None:
        topics = self._load()
        for idx, topic in enumerate(topics):
            if topic.get("topic_id") == topic_id:
                topic.update(patch)
                topics[idx] = topic
                self._save(topics)
                return topic
        return None

    def delete(self, topic_id: str) -> bool:
        topics = self._load()
        new_topics = [t for t in topics if t.get("topic_id") != topic_id]
        if len(new_topics) == len(topics):
            return False
        self._save(new_topics)
        return True

    def list_topics(self) -> list[dict]:
        return self._load()

    def search_by_alias(self, query: str, k: int = 10) -> list[dict]:
        nq = normalize_alias(query)
        matches: list[dict] = []
        for topic in self._load():
            aliases = topic.get("aliases", [])
            normalized_aliases = [normalize_alias(a) for a in aliases]
            if any(nq in a or a in nq for a in normalized_aliases if a):
                matches.append(topic)

        matches.sort(key=lambda t: t.get("time", {}).get("last_seen_at", ""), reverse=True)
        return matches[:k]

    def upsert_by_alias_overlap(self, name: str, one_liner: str, aliases: list[str], now_iso: str) -> dict:
        normalized = {normalize_alias(a) for a in aliases if normalize_alias(a)}
        topics = self._load()
        for idx, topic in enumerate(topics):
            existing = {normalize_alias(a) for a in topic.get("aliases", []) if normalize_alias(a)}
            if normalized.intersection(existing):
                merged_aliases = sorted(set(topic.get("aliases", []) + aliases))
                topic["aliases"] = merged_aliases
                topic["one_liner"] = one_liner or topic.get("one_liner", "")
                topic.setdefault("time", {})["last_seen_at"] = now_iso
                stats = topic.setdefault("stats", {"utility_score": 0.0, "touch_count": 0})
                stats["touch_count"] = int(stats.get("touch_count", 0)) + 1
                topics[idx] = topic
                self._save(topics)
                return topic

        topic = Topic(
            schema_version=1,
            topic_id=f"topic-{len(topics)+1}",
            name=name,
            one_liner=one_liner,
            aliases=sorted(set(aliases)),
            time=TopicTime(first_seen_at=now_iso, last_seen_at=now_iso, notable_events=[]),
            stats={"utility_score": 1.0, "touch_count": 1},
        ).to_dict()
        topics.append(topic)
        self._save(topics)
        return topic
