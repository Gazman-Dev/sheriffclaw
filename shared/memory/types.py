from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class NumberEntry:
    key: str
    value: int | float
    unit: str | None = None
    at: str = ""
    source: str | None = None
    confidence: float | None = None


@dataclass
class NotableEvent:
    at: str
    event: str


@dataclass
class TopicTime:
    first_seen_at: str
    last_seen_at: str
    notable_events: list[NotableEvent] = field(default_factory=list)


@dataclass
class Topic:
    schema_version: int
    topic_id: str
    name: str
    one_liner: str
    facts: list[str] = field(default_factory=list)
    numbers: list[NumberEntry] = field(default_factory=list)
    open_loops: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    time: TopicTime | None = None
    links: dict = field(default_factory=lambda: {"related_topic_ids": [], "skill_refs": [], "artifact_refs": []})
    stats: dict = field(default_factory=lambda: {"utility_score": 0.0, "touch_count": 0})

    def to_dict(self) -> dict:
        data = asdict(self)
        if self.time is not None:
            data["time"] = asdict(self.time)
        return data


@dataclass
class WakePacket:
    schema_version: int
    slept_at: str
    conversation_tail: list[dict]
    active_subject_hints: list[str]
    top_topic_ids: list[str]
    recent_skill_refs: list[str]
    in_progress: dict

    def to_dict(self) -> dict:
        return asdict(self)
