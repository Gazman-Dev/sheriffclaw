from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from shared.memory.config import RetrievalConfig
from shared.memory.embedding import EmbeddingProvider
from shared.memory.semantic_index import SemanticIndex
from shared.memory.store import TopicStore


DEEP_TRIGGER_TERMS = {
    "remember",
    "last time",
    "last week",
    "before sleep",
    "same bug",
    "anyway",
    "separately",
    "new thing",
}



@dataclass
class RetrievalResult:
    topics: list[dict]
    deep_used: bool
    trigger_reasons: list[str]


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _time_window(query: str, now_utc: datetime, wake_packet: dict | None) -> tuple[datetime | None, datetime | None, str | None]:
    q = query.lower()
    if "yesterday" in q:
        start = (now_utc - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return start, end, "yesterday"
    if "last week" in q:
        return now_utc - timedelta(days=7), now_utc, "last week"
    if "before sleep" in q and wake_packet:
        slept_at = _parse_iso(wake_packet.get("slept_at"))
        if slept_at:
            return datetime(1970, 1, 1, tzinfo=timezone.utc), slept_at, "before sleep"
    return None, None, None


def _in_window(last_seen: datetime | None, start: datetime | None, end: datetime | None) -> bool:
    if last_seen is None:
        return False
    if start and last_seen < start:
        return False
    if end and last_seen > end:
        return False
    return True


def _recency_boost(last_seen_iso: str | None, now_utc: datetime) -> float:
    last_seen = _parse_iso(last_seen_iso)
    if last_seen is None:
        return 0.0
    age_hours = max((now_utc - last_seen).total_seconds() / 3600.0, 0.0)
    return max(0.0, 0.2 - min(age_hours / (24 * 7), 0.2))


def _time_boost(last_seen_iso: str | None, start: datetime | None, end: datetime | None, boost: float) -> float:
    return boost if _in_window(_parse_iso(last_seen_iso), start, end) else 0.0


def _dedupe_by_topic_id(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        tid = it.get("topic_id")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        out.append(it)
    return out


def _build_topic_map(store: TopicStore) -> dict[str, dict]:
    return {t["topic_id"]: t for t in store.list_topics() if "topic_id" in t}


def _semantic_search(index: SemanticIndex, embedder: EmbeddingProvider, query: str, k: int) -> list[tuple[str, float]]:
    qv = embedder.embed_batch([query])[0]
    return index.search(qv, k=k)


def _trigger_reasons(query: str) -> list[str]:
    q = query.lower()
    return [term for term in DEEP_TRIGGER_TERMS if term in q]


def sync_semantic_index(topic_store: TopicStore, embedding_provider: EmbeddingProvider, semantic_index: SemanticIndex) -> None:
    topics = [t for t in topic_store.list_topics() if t.get("topic_id")]
    texts = [(t.get("one_liner") or t.get("name") or "") for t in topics]
    vectors = embedding_provider.embed_batch(texts)
    for t, v in zip(topics, vectors):
        semantic_index.upsert(t["topic_id"], v)


def retrieve_topics(
    query: str,
    now_iso: str,
    wake_packet: dict | None,
    topic_store: TopicStore,
    embedding_provider: EmbeddingProvider,
    semantic_index: SemanticIndex,
    force_deep: bool = False,
    config: RetrievalConfig | None = None,
) -> RetrievalResult:
    cfg = config or RetrievalConfig()
    now_utc = _parse_iso(now_iso) or datetime.now(timezone.utc)

    # Light retrieval (always)
    alias_hits = topic_store.search_by_alias(query, k=cfg.light_alias_k)
    semantic_hits = _semantic_search(semantic_index, embedding_provider, query, k=cfg.light_semantic_k)

    topic_map = _build_topic_map(topic_store)
    semantic_topics = [{**topic_map[tid], "_semantic_score": score} for tid, score in semantic_hits if tid in topic_map]

    merged = _dedupe_by_topic_id(alias_hits + semantic_topics)
    merged.sort(key=lambda t: t.get("time", {}).get("last_seen_at", ""), reverse=True)

    reasons = _trigger_reasons(query)
    top_score = semantic_hits[0][1] if semantic_hits else 0.0
    second_score = semantic_hits[1][1] if len(semantic_hits) > 1 else 0.0
    low_conf = top_score < cfg.low_conf_semantic_threshold or (top_score - second_score) < cfg.low_conf_margin

    deep_needed = force_deep or bool(reasons) or low_conf
    if not deep_needed:
        return RetrievalResult(topics=merged, deep_used=False, trigger_reasons=reasons + (["low-confidence"] if low_conf else []))

    # Deep retrieval
    alias_deep = topic_store.search_by_alias(query, k=cfg.deep_alias_k)
    semantic_deep = _semantic_search(semantic_index, embedding_provider, query, k=cfg.deep_semantic_k)

    start, end, _ = _time_window(query, now_utc, wake_packet)
    scored: dict[str, tuple[dict, float]] = {}

    alias_ids = {t.get("topic_id") for t in alias_deep}
    for t in alias_deep:
        tid = t.get("topic_id")
        if not tid:
            continue
        rec = _recency_boost(t.get("time", {}).get("last_seen_at"), now_utc)
        tm = _time_boost(t.get("time", {}).get("last_seen_at"), start, end, cfg.time_window_boost)
        score = cfg.alias_boost + rec + tm
        scored[tid] = (t, max(scored.get(tid, (t, -1e9))[1], score))

    for tid, sem_score in semantic_deep:
        t = topic_map.get(tid)
        if not t:
            continue
        alias_boost = cfg.alias_boost if tid in alias_ids else 0.0
        rec = _recency_boost(t.get("time", {}).get("last_seen_at"), now_utc)
        tm = _time_boost(t.get("time", {}).get("last_seen_at"), start, end, cfg.time_window_boost)
        final_score = sem_score + alias_boost + rec + tm
        scored[tid] = (t, max(scored.get(tid, (t, -1e9))[1], final_score))

    ranked = [topic for topic, _ in sorted(scored.values(), key=lambda x: x[1], reverse=True)]
    return RetrievalResult(topics=ranked, deep_used=True, trigger_reasons=reasons + (["low-confidence"] if low_conf else []))


def render_topic_md(topic: dict[str, Any]) -> str:
    lines = [f"### {topic.get('name', 'Untitled Topic')}"]
    if topic.get("one_liner"):
        lines.append(f"- Summary: {topic['one_liner']}")
    aliases = topic.get("aliases", [])
    if aliases:
        lines.append(f"- Aliases: {', '.join(aliases)}")
    t = topic.get("time", {})
    if t.get("first_seen_at") or t.get("last_seen_at"):
        lines.append(f"- Time: first_seen={t.get('first_seen_at','')}, last_seen={t.get('last_seen_at','')}")
    facts = topic.get("facts", [])
    if facts:
        lines.append("- Facts:")
        for f in facts[:6]:
            lines.append(f"  - {f}")
    loops = topic.get("open_loops", [])
    if loops:
        lines.append("- Open loops:")
        for l in loops[:6]:
            lines.append(f"  - {l}")
    return "\n".join(lines)
