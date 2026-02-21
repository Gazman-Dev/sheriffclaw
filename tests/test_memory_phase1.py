from datetime import datetime, timezone

from shared.memory.runtime import sleep, wake
from shared.memory.store import TopicStore
from shared.memory.types import Topic, TopicTime


def test_phase1_sleep_wake_alias_retrieval(tmp_path):
    store = TopicStore(tmp_path / "topics.json")

    conversation = []
    for i in range(30):
        conversation.append({"role": "user", "content": f"turn {i} planning details for the party logistics"})
        conversation.append({"role": "assistant", "content": f"ack turn {i} about party tasks"})

    slept = sleep(conversation, datetime.now(timezone.utc).isoformat(), store, keep_tail_turns=8)
    wake_packet = slept["wake_packet"]

    assert slept["topics_updated"] >= 1
    assert len(slept["trimmed_conversation"]) == 8
    assert wake_packet["schema_version"] == 1

    resumed = wake(wake_packet, "remember the party", datetime.now(timezone.utc).isoformat(), store)
    topics = resumed["retrieved_topics"]

    assert len(topics) >= 1
    assert any("party" in a.lower() for a in topics[0].get("aliases", []))


def test_alias_glue_words_are_not_indexed(tmp_path):
    store = TopicStore(tmp_path / "topics.json")
    conversation = [
        {"role": "user", "content": "noted noted noted this is just glue"},
        {"role": "assistant", "content": "noted"},
    ]

    sleep(conversation, datetime.now(timezone.utc).isoformat(), store, keep_tail_turns=0)

    assert store.search_by_alias("noted", k=5) == []


def test_alias_search_recency_tie_break(tmp_path):
    store = TopicStore(tmp_path / "topics.json")

    older = Topic(
        schema_version=1,
        topic_id="topic-old",
        name="Party Old",
        one_liner="old",
        aliases=["party"],
        time=TopicTime(first_seen_at="2026-01-01T00:00:00Z", last_seen_at="2026-01-01T00:00:00Z", notable_events=[]),
    )
    newer = Topic(
        schema_version=1,
        topic_id="topic-new",
        name="Party New",
        one_liner="new",
        aliases=["party"],
        time=TopicTime(first_seen_at="2026-01-02T00:00:00Z", last_seen_at="2026-01-02T00:00:00Z", notable_events=[]),
    )

    store.create(older)
    store.create(newer)

    out = store.search_by_alias("party", k=5)
    assert len(out) == 2
    assert out[0]["topic_id"] == "topic-new"
