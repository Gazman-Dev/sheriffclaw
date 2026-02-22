from __future__ import annotations


async def run(payload: dict, *, emit_event=None, context=None):
    text = payload.get("text") or payload.get("stdin", "")
    summary = (text or "").strip().replace("\n", " ")
    if len(summary) > 160:
        summary = summary[:157] + "..."
    if emit_event is not None:
        await emit_event("skill.delta", {"text": "summarizing"})
    return {"summary": summary, "chars": len(text or "")}
