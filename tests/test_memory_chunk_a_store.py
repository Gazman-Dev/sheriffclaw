from shared.memory.store import TopicStore
from shared.memory.types import EdgeType, Topic, TopicTime


def _mk_topic(topic_id: str, name: str, ts: str):
    return Topic(
        schema_version=1,
        topic_id=topic_id,
        name=name,
        one_liner=name,
        aliases=[name.lower()],
        time=TopicTime(first_seen_at=ts, last_seen_at=ts, notable_events=[]),
        stats={"utility_score": 0.0, "touch_count": 0, "last_utility_update_at": ts},
    )


def test_edge_persistence_round_trip(tmp_path):
    store = TopicStore(tmp_path / "topics.json")
    store.create(_mk_topic("t1", "A", "2026-01-01T00:00:00Z"))
    store.create(_mk_topic("t2", "B", "2026-01-01T00:00:00Z"))

    store.upsert_edge("t1", "t2", EdgeType.RELATES_TO, 0.8, "2026-01-02T00:00:00Z")

    store2 = TopicStore(tmp_path / "topics.json")
    edges = store2.list_edges()
    assert len(edges) == 1
    e = edges[0]
    assert e["from_topic_id"] == "t1"
    assert e["to_topic_id"] == "t2"
    assert e["edge_type"] == "RELATES_TO"
    assert e["weight"] == 0.8


def test_neighbor_lookup_with_type_filter(tmp_path):
    store = TopicStore(tmp_path / "topics.json")
    store.create(_mk_topic("t1", "A", "2026-01-01T00:00:00Z"))
    store.create(_mk_topic("t2", "B", "2026-01-01T00:00:00Z"))
    store.create(_mk_topic("t3", "C", "2026-01-01T00:00:00Z"))

    store.upsert_edge("t1", "t2", EdgeType.RELATES_TO, 0.7, "2026-01-02T00:00:00Z")
    store.upsert_edge("t1", "t3", EdgeType.DEPENDS_ON, 0.9, "2026-01-02T00:00:00Z")

    all_n = store.get_neighbors("t1")
    dep_n = store.get_neighbors("t1", EdgeType.DEPENDS_ON)

    assert len(all_n) == 2
    assert len(dep_n) == 1
    assert dep_n[0]["to_topic_id"] == "t3"


def test_utility_bump_and_decay_math_fixed_timestamps(tmp_path):
    store = TopicStore(tmp_path / "topics.json")
    store.create(_mk_topic("t1", "A", "2026-01-01T00:00:00Z"))

    # Initial bump at t0
    t = store.update_utility("t1", delta=10.0, now_iso="2026-01-01T00:00:00Z", decay_per_day=0.98)
    assert t is not None
    assert abs(t["stats"]["utility_score"] - 10.0) < 1e-9

    # +1 day decay then +2 bump
    t = store.update_utility("t1", delta=2.0, now_iso="2026-01-02T00:00:00Z", decay_per_day=0.98)
    assert t is not None
    expected = 10.0 * 0.98 + 2.0
    assert abs(t["stats"]["utility_score"] - expected) < 1e-9

    # Pure function check
    assert abs(TopicStore.decay_utility_value(10.0, 2.0, 0.98) - (10.0 * (0.98**2))) < 1e-9
