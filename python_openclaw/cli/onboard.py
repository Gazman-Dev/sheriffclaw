from __future__ import annotations

import base64
import json
from pathlib import Path


def run_onboard(base_dir: Path) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    print("OpenClaw onboarding wizard")
    keys = {
        "openai": input("OpenAI API key (optional): ").strip(),
        "anthropic": input("Anthropic API key (optional): ").strip(),
        "google": input("Google API key (optional): ").strip(),
        "moonshot": input("Moonshot API key (optional): ").strip(),
    }
    telegram_bot_token = input("Telegram bot token: ").strip()

    secrets_blob = base64.b64encode(json.dumps({"api_keys": keys, "telegram_bot_token": telegram_bot_token}).encode("utf-8"))
    (base_dir / "secrets.enc").write_bytes(secrets_blob)

    cfg = {
        "agents": {
            "defaults": {
                "model": {
                    "primary": "moonshot/kimi-best",
                    "fallbacks": ["anthropic/claude-best", "openai/best", "google/flash"],
                }
            }
        }
    }
    (base_dir / "openclaw.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    workspace = base_dir / "workspace"
    workspace.mkdir(exist_ok=True)
    (workspace / "SOUL.md").write_text("# SOUL\n\nYou are OpenClaw.", encoding="utf-8")
    (workspace / "USER.md").write_text("# USER\n\nDescribe your preferences.", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("# AGENTS\n\nLocal agent directives go here.", encoding="utf-8")

    print(f"Wrote config and workspace under {base_dir}")


if __name__ == "__main__":
    run_onboard(Path("."))
