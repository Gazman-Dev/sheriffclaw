from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from shared.memory.embedding import EmbeddingProvider
from shared.memory.semantic_index import SemanticIndex
from shared.memory.store import TopicStore
from shared.memory.types import Topic, TopicTime, WakePacket

_STOPWORDS = {
    "the", "this", "that", "with", "from", "have", "will", "about", "there",
    "their", "just", "your", "into", "when", "were", "what", "where", "would",
    "could", "should", "been", "because", "after", "before", "while", "then",
    "them", "also", "very",
}

_GLUE_WORDS = {
    "noted", "turn", "prepare", "planning", "details", "item", "list",
    "about", "thing", "stuff", "okay", "great", "thanks", "thank", "please",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_alias_token(token: str) -> bool:
    t = token.strip().lower()
    return (
            len(t) >= 4
            and any(ch.isalpha() for ch in t)
            and t not in _STOPWORDS
            and t not in _GLUE_WORDS
    )


def _extract_aliases(messages: list[dict]) -> list[str]:
    user_text = " ".join(str(m.get("content", "")) for m in messages if m.get("role") == "user")
    raw_tokens = [t.lower() for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", user_text)]
    tokens = [t for t in raw_tokens if _is_alias_token(t)]

    # noun-phrase-ish heuristic: adjacent valid tokens become 2-word aliases
    phrases: list[str] = []
    for i in range(len(tokens) - 1):
        phrases.append(f"{tokens[i]} {tokens[i+1]}")

    ranked = [a for a, _ in Counter(tokens + phrases).most_common(12)]
    return ranked


def _build_one_liner(messages: list[dict]) -> str:
    text = " ".join(str(m.get("content", "")) for m in messages).strip()
    if not text:
        return "Conversation summary"
    tokens = text.split()
    return " ".join(tokens[:24])


def sleep(
        conversation_buffer: list[dict],
        now: str | None,
        topic_store: TopicStore,
        keep_tail_turns: int = 10,
        embedding_provider: EmbeddingProvider | None = None,
        semantic_index: SemanticIndex | None = None,
) -> dict:
    """Compact conversation and emit stable sleep result."""
    now_iso = now or _now_iso()
    if keep_tail_turns < 0:
        keep_tail_turns = 0

    # Apply global time decay to existing utility scores before we evaluate usage
    topic_store.apply_decay(now_iso)

    if keep_tail_turns == 0:
        tail = []
        compacted = conversation_buffer[:]
    elif len(conversation_buffer) <= keep_tail_turns:
        tail = conversation_buffer[:]
        compacted = []
    else:
        tail = conversation_buffer[-keep_tail_turns:]
        compacted = conversation_buffer[:-keep_tail_turns]

    aliases = _extract_aliases(compacted)
    touched_topic_ids: list[str] = []

    # Touch topics per alias candidate (create or merge by alias overlap)
    for alias in aliases:
        topic = topic_store.upsert_by_alias_overlap(
            name=alias.title(),
            one_liner=_build_one_liner(compacted),
            aliases=[alias],
            now_iso=now_iso,
        )
        tid = topic.get("topic_id")
        if tid and tid not in touched_topic_ids:
            touched_topic_ids.append(tid)

    # Utility bump hooks (simple chunk-B rules)
    compact_text = " ".join(str(m.get("content", "")) for m in compacted).lower()
    correction_signal = any(x in compact_text for x in ["you are wrong", "incorrect", "that's wrong", "correction"])
    skill_success_signal = any(
        m.get("role") == "tool" and ("\"ok\": true" in str(m.get("content", "")).lower() or "status\": \"success\"" in str(m.get("content", "")).lower())
        for m in compacted
    )

    for tid in touched_topic_ids:
        topic_store.update_utility(tid, delta=1.0, now_iso=now_iso)
        if correction_signal:
            topic_store.update_utility(tid, delta=3.0, now_iso=now_iso)
        if skill_success_signal:
            topic_store.update_utility(tid, delta=2.0, now_iso=now_iso)

    # Co-activation linking: pairwise RELATES_TO edge bump
    if len(touched_topic_ids) > 1:
        for i in range(len(touched_topic_ids)):
            for j in range(i + 1, len(touched_topic_ids)):
                topic_store.link_topics(
                    touched_topic_ids[i],
                    touched_topic_ids[j],
                    "RELATES_TO",
                    0.5,
                    now_iso,
                    mode="add",
                    bidirectional_relates=True,
                    max_weight=5.0,
                )

    top_topic_ids: list[str] = touched_topic_ids[:]

    packet = WakePacket(
        schema_version=1,
        slept_at=now_iso,
        conversation_tail=tail,
        active_subject_hints=aliases[:3],
        top_topic_ids=top_topic_ids,
        recent_skill_refs=[],
        in_progress={"status": "idle", "resume_hint": "", "topic_id": top_topic_ids[0] if top_topic_ids else ""},
    )

    return {
        "wake_packet": packet.to_dict(),
        "trimmed_conversation": tail,
        "topics_updated": len(top_topic_ids),
    }


def wake(wake_packet: dict, user_msg: str, now: str | None, topic_store: TopicStore) -> dict:
    _ = now or _now_iso()
    retrieved = topic_store.search_by_alias(user_msg, k=8)
    return {
        "wake_packet": wake_packet,
        "retrieved_topics": retrieved,
        "resume_plan": {
            "status": wake_packet.get("in_progress", {}).get("status", "idle"),
            "hint": wake_packet.get("in_progress", {}).get("resume_hint", ""),
        },
    }