from __future__ import annotations

import getpass
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from python_openclaw.gateway.secrets.service import SecretsService

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


def _bool_prompt(prompt: str) -> bool:
    while True:
        raw = input(f"{prompt} [y/n]: ").strip().lower()
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False


def _telegram_get_updates(token: str, *, timeout: int = 20) -> list[dict]:
    query = urllib.parse.urlencode({"timeout": timeout, "allowed_updates": json.dumps(["message"])})
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates?{query}", timeout=timeout + 5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError("telegram getUpdates failed")
    return [item for item in payload.get("result", []) if isinstance(item, dict)]


def _wait_for_bot_message(token: str, bot_label: str) -> tuple[int, str]:
    print(f"Send a message to your {bot_label} bot now. Waiting up to 120 seconds...")
    started = time.time()
    while time.time() - started < 120:
        updates = _telegram_get_updates(token, timeout=10)
        for item in reversed(updates):
            msg = item.get("message") or {}
            user = msg.get("from") or {}
            text = msg.get("text")
            if text and "id" in user:
                print(f"{bot_label} echo candidate -> user_id={user['id']} text={text!r}")
                if _bool_prompt("Confirm this user/message?"):
                    return int(user["id"]), str(text)
        time.sleep(1)
    raise RuntimeError(f"No {bot_label} message confirmed during onboarding")


def run_onboard(base_dir: Path) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    print("Sheriff Claw onboarding wizard")

    master_password = getpass.getpass("Choose master password: ")
    selected = _select_provider()
    provider_key = getpass.getpass(f"Provide {selected} API key/token: ")

    llm_bot_token = input("Telegram LLM bot token: ").strip()
    secrets_bot_token = input("Telegram Secrets bot token: ").strip()
    allow_telegram_master_password = _bool_prompt("Do you want to send master password via Telegram?")

    service = SecretsService(
        encrypted_path=base_dir / "secrets_service.enc",
        master_verifier_path=base_dir / "master.json",
        telegram_secrets_path=base_dir / "telegram_secrets_channel.json",
    )
    service.initialize(
        master_password=master_password,
        provider=selected,
        llm_api_key=provider_key,
        llm_bot_token=llm_bot_token,
        gate_bot_token=secrets_bot_token,
        allow_telegram_master_password=allow_telegram_master_password,
    )

    llm_user_id, _ = _wait_for_bot_message(llm_bot_token, "LLM")
    gate_user_id, _ = _wait_for_bot_message(secrets_bot_token, "Secrets")

    identity_state = service.get_identity_state()
    identity_state["llm_allowed_telegram_user_ids"] = sorted({*identity_state["llm_allowed_telegram_user_ids"], llm_user_id})
    identity_state["trusted_gate_user_ids"] = sorted({*identity_state["trusted_gate_user_ids"], gate_user_id})
    identity_state["gate_bindings"][f"tg:{llm_user_id}"] = f"tg:dm:{gate_user_id}"
    service.save_identity_state(identity_state)

    cfg = {
        "llm_provider": selected,
        "allow_telegram_master_password": allow_telegram_master_password,
    }
    (base_dir / "openclaw.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    _ensure_identity_templates(base_dir / "workspace")
    service.lock()
    print(f"Wrote v1 config under {base_dir}")


if __name__ == "__main__":
    run_onboard(Path("."))
