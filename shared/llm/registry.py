"""
Intentionally emptied.
Models and registry behavior are configured directly inside the repo-backed Codex MCP environment.
"""


def resolve_model(model_ref: str | None) -> str:
    return model_ref or ""
