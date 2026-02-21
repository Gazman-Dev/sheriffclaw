from datetime import datetime, timezone

from shared.memory.runtime import sleep, wake
from shared.memory.store import TopicStore


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
