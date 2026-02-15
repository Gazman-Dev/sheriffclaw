from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Frame:
    type: str
    id: str
    name: str
    payload: dict[str, Any]
