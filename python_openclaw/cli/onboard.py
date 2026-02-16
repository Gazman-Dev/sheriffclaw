from __future__ import annotations

import getpass
import json
from pathlib import Path

from python_openclaw.gateway.credentials import CredentialStore
from python_openclaw.gateway.identity_store import IdentityStore
from python_openclaw.gateway.master_password import create_verifier
from python_openclaw.gateway.secrets.store import SecretStore

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
    mode = input("Credential mode (A=plaintext telegram, B=encrypted everything) [A/B]: ").strip().lower()
    encrypted_mode = mode == "b"
    storage_mode = "encrypted" if encrypted_mode else "plaintext"

    master_password = ""
    if encrypted_mode:
        master_password = getpass.getpass("Master password: ")
        (base_dir / "master.json").write_text(json.dumps(create_verifier(master_password), indent=2), encoding="utf-8")

    agent_token = input("Telegram agent token: ").strip()
    gate_token = input("Telegram gate token: ").strip()
    provider_key = getpass.getpass(f"{selected} API key (empty allowed): ")

    cfg = {
        "agents": {"defaults": {"model": {"primary": f"{selected}/best", "fallbacks": []}}},
        "provider": selected,
        "users": [],
        "gate_users": [],
        "storage_mode": storage_mode,
        "unlock_host": "127.0.0.1",
        "unlock_port": 8443,
    }
    (base_dir / "openclaw.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    credentials = {
        "telegram": {"agent_token": agent_token, "gate_token": gate_token},
        "llm": {
            "openai_api_key": provider_key if selected == "openai" else "",
            "anthropic_api_key": provider_key if selected == "anthropic" else "",
            "google_api_key": provider_key if selected == "google" else "",
            "moonshot_api_key": provider_key if selected == "moonshot" else "",
        },
    }
    credential_store = CredentialStore(base_dir / "credentials.json", base_dir / "credentials.enc", mode=storage_mode)
    credential_store.set_initial(credentials, master_password=master_password if encrypted_mode else None)

    identity_store = IdentityStore(base_dir / "identity.json", base_dir / "identity.enc", mode="encrypted" if encrypted_mode else "plaintext")
    identity_store.persist_unlocked({"llm_allowed_telegram_user_ids": [], "gate_bindings": {}}, master_password=master_password)

    secret_store = SecretStore(base_dir / "secrets.enc")
    secret_store.unlock(master_password if encrypted_mode else "")

    _ensure_identity_templates(base_dir / "workspace")
    print(f"Wrote config and workspace under {base_dir}")


if __name__ == "__main__":
    run_onboard(Path("."))
