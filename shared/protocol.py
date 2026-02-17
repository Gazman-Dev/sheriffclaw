from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RequestFrame:
    id: str
    op: str
    payload: dict[str, Any]


@dataclass(slots=True)
class EventFrame:
    id: str
    event: str
    payload: dict[str, Any]


def ok_response(req_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {"id": req_id, "ok": True, "result": result}


def error_response(req_id: str, error: str, error_type: str = "error", details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": req_id, "ok": False, "error": error, "error_type": error_type, "details": details or {}}
