from __future__ import annotations

import json
from pathlib import Path


SUPPORTED_PROVIDERS = ("openai", "anthropic", "google", "moonshot")


def _ensure_identity_templates(workspace: Path) -> None:
    workspace.mkdir(exist_ok=True)
    defaults = {
        "SOUL.md": "# SOUL\n\nYou are Sheriff Claw.",
        "AGENTS.md": "# AGENTS\n\nLocal agent directives go here.",
        "USER.md": "# USER\n\nDescribe your preferences.",
    }
    for name, content in defaults.items():
        path = workspace / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")


def _select_provider() -> str:
    print("Supported providers:")
    for idx, provider in enumerate(SUPPORTED_PROVIDERS, start=1):
        print(f"  {idx}. {provider}")

    while True:
        raw = input(f"Select provider [1-{len(SUPPORTED_PROVIDERS)}]: ").strip()
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(SUPPORTED_PROVIDERS):
                return SUPPORTED_PROVIDERS[index - 1]


def run_onboard(base_dir: Path) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    print("Sheriff Claw onboarding wizard")

    selected = _select_provider()

    cfg = {
        "agents": {"defaults": {"model": {"primary": f"{selected}/best", "fallbacks": []}}},
        "provider": selected,
        "users": [],
    }
    (base_dir / "openclaw.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    _ensure_identity_templates(base_dir / "workspace")
    print(f"Wrote config and workspace under {base_dir}")


if __name__ == "__main__":
    run_onboard(Path("."))
