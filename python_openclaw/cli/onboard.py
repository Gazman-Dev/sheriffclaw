from __future__ import annotations

import base64
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


def run_onboard(base_dir: Path) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    print("Sheriff Claw onboarding wizard")

    print("Supported providers:")
    for idx, provider in enumerate(SUPPORTED_PROVIDERS, start=1):
        print(f"  {idx}. {provider}")

    selected = ""
    while selected not in SUPPORTED_PROVIDERS:
        raw = input("Select provider by name: ").strip().lower()
        if raw in SUPPORTED_PROVIDERS:
            selected = raw

    api_key = ""
    while not api_key:
        api_key = input(f"{selected} API key (required): ").strip()

    agent_token = ""
    while not agent_token:
        agent_token = input("OPENCLAW_AGENT_TOKEN: ").strip()

    gate_token = ""
    while not gate_token:
        gate_token = input("OPENCLAW_GATE_TOKEN: ").strip()

    secrets_blob = base64.b64encode(
        json.dumps(
            {
                "api_keys": {selected: api_key},
                "telegram": {
                    "OPENCLAW_AGENT_TOKEN": agent_token,
                    "OPENCLAW_GATE_TOKEN": gate_token,
                },
            }
        ).encode("utf-8")
    )
    (base_dir / "secrets.enc").write_bytes(secrets_blob)

    cfg = {
        "agents": {"defaults": {"model": {"primary": f"{selected}/best", "fallbacks": []}}},
        "provider": selected,
    }
    (base_dir / "openclaw.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    _ensure_identity_templates(base_dir / "workspace")
    print(f"Wrote config and workspace under {base_dir}")


if __name__ == "__main__":
    run_onboard(Path("."))
