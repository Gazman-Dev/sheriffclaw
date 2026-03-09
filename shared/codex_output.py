from __future__ import annotations

from typing import Any


def extract_text_content(result: dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return ""

    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        content = structured.get("content")
        if isinstance(content, str) and content.strip():
            return content

    items = result.get("content")
    if isinstance(items, list):
        parts: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        if parts:
            return "".join(parts)

    text = result.get("text")
    if isinstance(text, str) and text.strip():
        return text

    return ""
