from __future__ import annotations


def resolve_model(model_ref: str | None) -> str:
    return model_ref or "gpt-5.3-codex"
