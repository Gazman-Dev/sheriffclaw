from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class Principal:
    principal_id: str
    role: str  # user | operator


@dataclass(slots=True)
class Binding:
    channel: str
    external_id: str
    principal_id: str


@dataclass(slots=True)
class ToolRequest:
    tool_name: str
    payload: dict[str, Any]
    reason: str | None = None


@dataclass(slots=True)
class Event:
    event_type: str
    payload: dict[str, Any]
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
