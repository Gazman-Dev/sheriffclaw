from __future__ import annotations

import uuid
from datetime import datetime, timezone

from shared.memory.embedding import EmbeddingProvider
from shared.memory.semantic_index import SemanticIndex
from shared.memory.store import TopicStore
from shared.memory.types import WakePacket


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_conversation_chunk(messages: list[dict]) -> str:
    """Converts a list of messages into a searchable text block."""
    lines = []
    for m in messages:
        role = m.get("role", "unknown").upper()
        content = m.get("content", "")
        lines.append(f"[{role}]: {content}")
    return "\n".join(lines)


def sleep(
        conversation_buffer: list[dict],
        now: str | None,
        topic_store: TopicStore,
        embedding_provider: EmbeddingProvider,
        topics_index: SemanticIndex,
        conversations_index: SemanticIndex,
        keep_tail_turns: int = 10,
) -> dict:
    """
    Compacts conversation:
    1. Indexes dropped messages into conversation vector memory.
    2. Updates topic utility scores.
    3. Produces a wake packet for session persistence.
    """
    now_iso = now or _now_iso()

    if len(conversation_buffer) <= keep_tail_turns:
        return {
            "wake_packet": None,
            "trimmed_conversation": conversation_buffer,
            "indexed_chunks": 0
        }

    # Slice the part that is leaving the active buffer
    compacted = conversation_buffer[:-keep_tail_turns]
    tail = conversation_buffer[-keep_tail_turns:]

    # Long-Term Conversation Indexing:
    # We chunk the dropped messages into groups of 5 for more granular searchability
    chunk_size = 5
    chunks_indexed = 0
    for i in range(0, len(compacted), chunk_size):
        chunk_msgs = compacted[i:i + chunk_size]
        chunk_text = _format_conversation_chunk(chunk_msgs)
        chunk_id = f"transcript-{uuid.uuid4().hex[:8]}-{now_iso}"

        # Embed the text block and save to conversation index
        vector = embedding_provider.embed(chunk_text)
        conversations_index.upsert(chunk_id, vector)

        # Also store the raw text in a companion file so search can retrieve it
        transcript_path = Path.cwd() / ".memory" / "transcripts"
        transcript_path.mkdir(parents=True, exist_ok=True)
        (transcript_path / f"{chunk_id}.txt").write_text(chunk_text, encoding="utf-8")
        chunks_indexed += 1

    # Save indices
    topics_index.save()
    conversations_index.save()

    packet = WakePacket(
        schema_version=1,
        slept_at=now_iso,
        conversation_tail=tail,
        active_subject_hints=[],
        top_topic_ids=[],
        recent_skill_refs=[],
        in_progress={"status": "idle"},
    )

    return {
        "wake_packet": packet.to_dict(),
        "trimmed_conversation": tail,
        "indexed_chunks": chunks_indexed,
    }


def wake(wake_packet: dict, user_msg: str, now: str | None, topic_store: TopicStore) -> dict:
    # Standard retrieval logic for starting a new session or resuming after sleep
    retrieved = topic_store.search_by_alias(user_msg, k=8)
    return {
        "wake_packet": wake_packet,
        "retrieved_topics": retrieved,
        "resume_plan": wake_packet.get("in_progress", {"status": "idle"}),
    }
