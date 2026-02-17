from __future__ import annotations

VERSION = "0.2.0"


def ok_response(req_id: str, result: dict) -> dict:
    return {"id": req_id, "ok": True, "result": result}


def error_response(req_id: str, error: str, error_type: str = "error", details: dict | None = None) -> dict:
    return {
        "id": req_id,
        "ok": False,
        "error": error,
        "error_type": error_type,
        "details": details or {},
    }
