from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from shared.memory.store import TopicStore
from shared.memory.types import WakePacket

_STOPWORDS = {
    "the",
    "this",
    "that",
    "with",
    "from",
    "have",
    "will",
    "about",
    "there",
    "their",
    "just",
    "your",
    "into",
    "when",
    "were",
    "what",
    "where",
    "would",
    "could",
    "should",
    "been",
    "because",
    "after",
    "before",
    "while",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_aliases(messages: list[dict]) -> list[str]:
    text = " ".join(str(m.get("content", "")) for m in messages)
    words = [w for w in re.findall(r"[a-zA-Z]{4,}", text.lower()) if w not in _STOPWORDS]
    top = [w for w, _ in Counter(words).most_common(8)]
    return top


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
) -> dict:
    now_iso = now or _now_iso()
    if keep_tail_turns < 0:
        keep_tail_turns = 0

    if len(conversation_buffer) <= keep_tail_turns:
        tail = conversation_buffer[:]
        compacted = []
    else:
        tail = conversation_buffer[-keep_tail_turns:]
        compacted = conversation_buffer[:-keep_tail_turns]

    aliases = _extract_aliases(compacted)
    top_topic_ids: list[str] = []
    if aliases:
        topic = topic_store.upsert_by_alias_overlap(
            name=aliases[0].title(),
            one_liner=_build_one_liner(compacted),
            aliases=aliases,
            now_iso=now_iso,
        )
        top_topic_ids.append(topic["topic_id"])

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
