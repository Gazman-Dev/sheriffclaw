from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from shared.memory.types import Topic, TopicEdge, TopicTime


def normalize_alias(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", text.lower())).strip()


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class TopicStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.edges_path = db_path.parent / f"{db_path.stem}_edges.json"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict]:
        if not self.db_path.exists():
            return []
        return json.loads(self.db_path.read_text(encoding="utf-8"))

    def _save(self, topics: list[dict]) -> None:
        self.db_path.write_text(json.dumps(topics, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_edges(self) -> list[dict]:
        if not self.edges_path.exists():
            return []
        return json.loads(self.edges_path.read_text(encoding="utf-8"))

    def _save_edges(self, edges: list[dict]) -> None:
        self.edges_path.write_text(json.dumps(edges, ensure_ascii=False, indent=2), encoding="utf-8")

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

        edges = self._load_edges()
        new_edges = [e for e in edges if e.get("from_topic_id") != topic_id and e.get("to_topic_id") != topic_id]
        self._save_edges(new_edges)

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

    def link_topics(self, from_id: str, to_id: str, edge_type: str, weight_delta: float, now_iso: str) -> None:
        if not from_id or not to_id or from_id == to_id:
            return

        edges = self._load_edges()
        for edge in edges:
            if edge.get("from_topic_id") == from_id and edge.get("to_topic_id") == to_id and edge.get("edge_type") == edge_type:
                edge["weight"] = edge.get("weight", 0.0) + weight_delta
                edge["last_updated_at"] = now_iso
                self._save_edges(edges)
                return

        new_edge = TopicEdge(
            from_topic_id=from_id,
            to_topic_id=to_id,
            edge_type=edge_type,
            weight=weight_delta,
            last_updated_at=now_iso,
        )
        edges.append(new_edge.to_dict())
        self._save_edges(edges)

    def get_adjacent_topics(self, topic_id: str) -> list[str]:
        edges = self._load_edges()
        adjacent = set()
        for edge in edges:
            if edge.get("from_topic_id") == topic_id:
                adjacent.add(edge.get("to_topic_id"))
            elif edge.get("to_topic_id") == topic_id:
                adjacent.add(edge.get("from_topic_id"))
        return list(adjacent)

    def apply_decay(self, now_iso: str) -> None:
        now = _parse_iso(now_iso)
        if not now:
            return

        topics = self._load()
        changed = False
        for topic in topics:
            last_seen = _parse_iso(topic.get("time", {}).get("last_seen_at"))
            if last_seen:
                days_since = max(0.0, (now - last_seen).total_seconds() / 86400.0)
                if days_since > 1.0:
                    stats = topic.setdefault("stats", {"utility_score": 0.0, "touch_count": 0})
                    old_util = stats.get("utility_score", 0.0)
                    if old_util > 0.1:
                        # decay old topics by time since last_seen (0.98 per day)
                        stats["utility_score"] = old_util * (0.98 ** days_since)
                        # sync last seen so we don't double decay heavily if called repeatedly
                        topic.setdefault("time", {})["last_seen_at"] = now_iso
                        changed = True

        if changed:
            self._save(topics)