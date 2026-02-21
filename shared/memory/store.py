from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from shared.memory.types import EdgeType, Topic, TopicEdge, TopicTime


def normalize_alias(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", text.lower())).strip()


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class TopicStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.edges_path = self.db_path.with_name("_edges.json")

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
        data = topic.to_dict()
        data.setdefault("stats", {})
        data["stats"].setdefault("utility_score", 0.0)
        data["stats"].setdefault("touch_count", 0)
        data["stats"].setdefault("last_utility_update_at", "")
        topics.append(data)
        self._save(topics)
        return data

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
        # remove incident edges
        edges = self._load_edges()
        edges = [e for e in edges if e.get("from_topic_id") != topic_id and e.get("to_topic_id") != topic_id]
        self._save_edges(edges)
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
                stats = topic.setdefault("stats", {"utility_score": 0.0, "touch_count": 0, "last_utility_update_at": ""})
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
            stats={"utility_score": 1.0, "touch_count": 1, "last_utility_update_at": now_iso},
        ).to_dict()
        topics.append(topic)
        self._save(topics)
        return topic

    # Edge CRUD
    def upsert_edge(
        self,
        from_topic_id: str,
        to_topic_id: str,
        edge_type: EdgeType | str,
        weight: float,
        last_updated_at: str,
    ) -> dict:
        et = edge_type.value if isinstance(edge_type, EdgeType) else str(edge_type)
        edges = self._load_edges()
        for i, e in enumerate(edges):
            if (
                e.get("from_topic_id") == from_topic_id
                and e.get("to_topic_id") == to_topic_id
                and e.get("edge_type") == et
            ):
                e["weight"] = float(weight)
                e["last_updated_at"] = last_updated_at
                edges[i] = e
                self._save_edges(edges)
                return e

        edge = TopicEdge(
            schema_version=1,
            from_topic_id=from_topic_id,
            to_topic_id=to_topic_id,
            edge_type=EdgeType(et),
            weight=float(weight),
            last_updated_at=last_updated_at,
        )
        data = {
            "schema_version": edge.schema_version,
            "from_topic_id": edge.from_topic_id,
            "to_topic_id": edge.to_topic_id,
            "edge_type": edge.edge_type.value,
            "weight": edge.weight,
            "last_updated_at": edge.last_updated_at,
        }
        edges.append(data)
        self._save_edges(edges)
        return data

    def list_edges(self) -> list[dict]:
        return self._load_edges()

    # Compatibility alias used by runtime/tests
    def link_topics(self, from_topic_id: str, to_topic_id: str, edge_type: EdgeType | str, weight: float, now_iso: str) -> dict:
        return self.upsert_edge(from_topic_id, to_topic_id, edge_type, weight, now_iso)

    def get_neighbors(self, topic_id: str, edge_type: EdgeType | str | None = None) -> list[dict]:
        et = None
        if edge_type is not None:
            et = edge_type.value if isinstance(edge_type, EdgeType) else str(edge_type)

        out = []
        for e in self._load_edges():
            if e.get("from_topic_id") != topic_id:
                continue
            if et and e.get("edge_type") != et:
                continue
            out.append(e)
        return out

    def get_adjacent_topics(self, topic_id: str, min_weight: float = 0.0) -> list[str]:
        adjacent: set[str] = set()
        for e in self._load_edges():
            w = float(e.get("weight", 0.0))
            if w < min_weight:
                continue
            if e.get("from_topic_id") == topic_id:
                adjacent.add(str(e.get("to_topic_id")))
            elif e.get("to_topic_id") == topic_id:
                adjacent.add(str(e.get("from_topic_id")))
        return sorted(adjacent)

    def delete_edge(self, from_topic_id: str, to_topic_id: str, edge_type: EdgeType | str) -> bool:
        et = edge_type.value if isinstance(edge_type, EdgeType) else str(edge_type)
        edges = self._load_edges()
        new_edges = [
            e
            for e in edges
            if not (
                e.get("from_topic_id") == from_topic_id
                and e.get("to_topic_id") == to_topic_id
                and e.get("edge_type") == et
            )
        ]
        if len(new_edges) == len(edges):
            return False
        self._save_edges(new_edges)
        return True

    # Utility math (store-layer only)
    def update_utility(self, topic_id: str, delta: float, now_iso: str, decay_per_day: float = 0.98) -> dict | None:
        topics = self._load()
        now_dt = _parse_iso(now_iso)
        if now_dt is None:
            raise ValueError("now_iso must be valid ISO-8601")

        for i, t in enumerate(topics):
            if t.get("topic_id") != topic_id:
                continue

            stats = t.setdefault("stats", {})
            current = float(stats.get("utility_score", 0.0))
            last_ts = stats.get("last_utility_update_at") or t.get("time", {}).get("last_seen_at")
            last_dt = _parse_iso(last_ts)

            decayed = current
            if last_dt is not None and now_dt >= last_dt:
                days = (now_dt - last_dt).total_seconds() / 86400.0
                decayed = current * (decay_per_day ** days)

            updated = decayed + float(delta)
            stats["utility_score"] = updated
            stats["last_utility_update_at"] = now_iso
            t["stats"] = stats
            topics[i] = t
            self._save(topics)
            return t
        return None

    def apply_decay(self, now_iso: str, decay_per_day: float = 0.98) -> None:
        topics = self._load()
        now_dt = _parse_iso(now_iso)
        if now_dt is None:
            raise ValueError("now_iso must be valid ISO-8601")

        changed = False
        for i, t in enumerate(topics):
            stats = t.setdefault("stats", {})
            current = float(stats.get("utility_score", 0.0))
            last_ts = stats.get("last_utility_update_at") or t.get("time", {}).get("last_seen_at")
            last_dt = _parse_iso(last_ts)
            if last_dt is None or now_dt < last_dt:
                continue
            days = (now_dt - last_dt).total_seconds() / 86400.0
            decayed = current * (decay_per_day ** days)
            stats["utility_score"] = decayed
            stats["last_utility_update_at"] = now_iso
            t["stats"] = stats
            topics[i] = t
            changed = True

        if changed:
            self._save(topics)

    @staticmethod
    def decay_utility_value(current_utility: float, elapsed_days: float, decay_per_day: float = 0.98) -> float:
        return float(current_utility) * (decay_per_day ** max(0.0, float(elapsed_days)))
