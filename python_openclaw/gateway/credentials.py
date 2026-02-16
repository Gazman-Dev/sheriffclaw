from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from python_openclaw.gateway.secrets.crypto import decrypt_blob, encrypt_blob


class CredentialStoreLockedError(RuntimeError):
    pass


class CredentialStore:
    def __init__(self, path_plain: Path, path_enc: Path, mode: str = "plaintext") -> None:
        self.path_plain = path_plain
        self.path_enc = path_enc
        self.mode = mode
        self._credentials: dict[str, Any] | None = None
        self.path_plain.parent.mkdir(parents=True, exist_ok=True)

    def is_encrypted_mode(self) -> bool:
        return self.mode == "encrypted"

    @property
    def unlocked(self) -> bool:
        if not self.is_encrypted_mode():
            return True
        return self._credentials is not None

    def exists(self) -> bool:
        return self.path_enc.exists() if self.is_encrypted_mode() else self.path_plain.exists()

    def unlock(self, master_password: str) -> None:
        if not self.is_encrypted_mode():
            return
        if not self.path_enc.exists() or self.path_enc.stat().st_size == 0:
            self._credentials = {}
            return
        data = decrypt_blob(self.path_enc.read_bytes(), master_password)
        self._credentials = _normalize_credentials(data)

    def lock(self) -> None:
        self._credentials = None

    def load(self) -> dict[str, Any]:
        if self.is_encrypted_mode():
            if self._credentials is None:
                raise CredentialStoreLockedError("credential store locked")
            return self._credentials
        if not self.path_plain.exists():
            return {}
        return _normalize_credentials(json.loads(self.path_plain.read_text(encoding="utf-8")))

    def get_telegram_tokens(self) -> tuple[str, str]:
        data = self.load()
        telegram = data.get("telegram", {})
        return str(telegram.get("agent_token", "")), str(telegram.get("gate_token", ""))

    def get_llm_keys(self) -> dict[str, str]:
        data = self.load()
        llm = data.get("llm", {})
        return {
            "openai": str(llm.get("openai_api_key", "")),
            "anthropic": str(llm.get("anthropic_api_key", "")),
            "google": str(llm.get("google_api_key", "")),
            "moonshot": str(llm.get("moonshot_api_key", "")),
        }

    def set_initial(self, credentials: dict[str, Any], master_password: str | None = None) -> None:
        normalized = _normalize_credentials(credentials)
        if self.is_encrypted_mode():
            if not master_password:
                raise ValueError("master_password is required for encrypted mode")
            self.path_enc.write_bytes(encrypt_blob(normalized, master_password))
            self._credentials = normalized
            return
        self.path_plain.write_text(json.dumps(normalized, indent=2), encoding="utf-8")


def _normalize_credentials(data: dict[str, Any]) -> dict[str, Any]:
    telegram = data.get("telegram", {}) if isinstance(data, dict) else {}
    llm = data.get("llm", {}) if isinstance(data, dict) else {}
    return {
        "telegram": {
            "agent_token": str(telegram.get("agent_token", "")),
            "gate_token": str(telegram.get("gate_token", "")),
        },
        "llm": {
            "openai_api_key": str(llm.get("openai_api_key", "")),
            "anthropic_api_key": str(llm.get("anthropic_api_key", "")),
            "google_api_key": str(llm.get("google_api_key", "")),
            "moonshot_api_key": str(llm.get("moonshot_api_key", "")),
        },
    }
