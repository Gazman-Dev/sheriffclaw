from __future__ import annotations


def session_key_for_message(channel: str, payload: dict) -> str:
    if channel == "telegram":
        chat_type = str(payload.get("chat_type") or "").strip().lower()
        chat_id = payload.get("chat_id")
        topic_id = payload.get("message_thread_id")
        if chat_type == "private":
            return "private_main"
        if chat_id is not None and topic_id is not None:
            return f"group_{chat_id}_topic_{topic_id}"
        if chat_id is not None:
            return f"group_{chat_id}_topic_main"
    principal_id = str(payload.get("principal_external_id") or "unknown").strip() or "unknown"
    return f"{channel}_{principal_id}"
