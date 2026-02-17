from __future__ import annotations

SKILL_NAME = "summarize"


async def run(payload: dict, *, emit_event):
    text = payload.get("text") or payload.get("stdin", "")
    if not text:
        text = ""
    summary = text.strip().replace("\n", " ")
    if len(summary) > 160:
        summary = summary[:157] + "..."
    await emit_event("skill.delta", {"text": "summarizing"})
    return {"summary": summary, "chars": len(text)}
