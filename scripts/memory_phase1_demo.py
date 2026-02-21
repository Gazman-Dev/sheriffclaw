from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.memory.runtime import sleep, wake
from shared.memory.store import TopicStore


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        store = TopicStore(Path(td) / "topics.json")

        conversation = []
        for i in range(20):
            conversation.append({"role": "user", "content": f"we should prepare the party playlist and food list turn {i}"})
            conversation.append({"role": "assistant", "content": f"noted party planning item {i}"})

        slept = sleep(conversation, datetime.now(timezone.utc).isoformat(), store, keep_tail_turns=6)
        packet = slept["wake_packet"]

        resumed = wake(packet, "remember the party", datetime.now(timezone.utc).isoformat(), store)
        topics = resumed["retrieved_topics"]

        print("SLEEP_TOPICS_UPDATED", slept["topics_updated"])
        print("SLEEP_TAIL_LEN", len(slept["trimmed_conversation"]))
        print("WAKE_TOPICS_FOUND", len(topics))
        if topics:
            print("WAKE_FIRST_TOPIC_NAME", topics[0].get("name"))
            print("WAKE_FIRST_TOPIC_ALIASES", ",".join(topics[0].get("aliases", [])))


if __name__ == "__main__":
    main()
