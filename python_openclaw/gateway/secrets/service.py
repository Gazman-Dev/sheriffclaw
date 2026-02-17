from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from python_openclaw.gateway.master_password import create_verifier, verify_password
from python_openclaw.gateway.secrets.crypto import decrypt_blob, encrypt_blob


class SecretsServiceLockedError(RuntimeError):
    pass


class SecretsService:
    """Single authority for auth + encrypted state (v1)."""

    def __init__(
        self,
        *,
        encrypted_path: Path,
        master_verifier_path: Path,
        telegram_secrets_path: Path,
    ) -> None:
        self.encrypted_path = encrypted_path
        self.master_verifier_path = master_verifier_path
        self.telegram_secrets_path = telegram_secrets_path
        self.encrypted_path.parent.mkdir(parents=True, exist_ok=True)
        self._password: str | None = None
        self._state: dict[str, Any] | None = None

    def initialize(
        self,
        *,
        master_password: str,
        provider: str,
        llm_api_key: str,
        llm_bot_token: str,
        gate_bot_token: str,
        allow_telegram_master_password: bool,
    ) -> None:
        self.master_verifier_path.write_text(json.dumps(create_verifier(master_password), indent=2), encoding="utf-8")
        self._password = master_password
        self._state = {
            "version": 1,
            "llm": {
                "provider": provider,
                "api_key": llm_api_key,
                "telegram_bot_token": llm_bot_token,
            },
            "gate": {
                "telegram_bot_token": "" if allow_telegram_master_password else gate_bot_token,
                "allow_telegram_master_password": allow_telegram_master_password,
            },
            "identity": {
                "llm_allowed_telegram_user_ids": [],
                "gate_bindings": {},
                "trusted_gate_user_ids": [],
            },
            "secrets": {},
        }
        self._persist_encrypted()
        if allow_telegram_master_password:
            self.telegram_secrets_path.write_text(
                json.dumps(
                    {
                        "telegram_bot_token": gate_bot_token,
                        "allow_telegram_master_password": True,
                        "trusted_gate_user_ids": [],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        elif self.telegram_secrets_path.exists():
            self.telegram_secrets_path.unlink()

    @property
    def unlocked(self) -> bool:
        return self._state is not None

    def verify_master_password(self, candidate: str) -> bool:
        if not self.master_verifier_path.exists():
            return False
        verifier = json.loads(self.master_verifier_path.read_text(encoding="utf-8"))
        return verify_password(candidate, verifier)

    def unlock(self, password: str) -> None:
        if self.encrypted_path.exists() and self.encrypted_path.stat().st_size > 0:
            self._state = self._normalize_state(decrypt_blob(self.encrypted_path.read_bytes(), password))
        else:
            self._state = self._normalize_state({})
        self._password = password

    def lock(self) -> None:
        self._state = None
        self._password = None

    def gate_channel_uses_plaintext_config(self) -> bool:
        if self.telegram_secrets_path.exists():
            data = json.loads(self.telegram_secrets_path.read_text(encoding="utf-8"))
            return bool(data.get("allow_telegram_master_password", False))
        if not self._state:
            return False
        return bool(self._state.get("gate", {}).get("allow_telegram_master_password", False))

    def get_gate_bot_token(self) -> str:
        if self.telegram_secrets_path.exists():
            data = json.loads(self.telegram_secrets_path.read_text(encoding="utf-8"))
            token = str(data.get("telegram_bot_token", ""))
            if token:
                return token
        return str(self._required_state()["gate"].get("telegram_bot_token", ""))

    def get_llm_bot_token(self) -> str:
        return str(self._required_state()["llm"].get("telegram_bot_token", ""))

    def get_provider(self) -> str:
        return str(self._required_state()["llm"].get("provider", "openai"))

    def get_llm_api_key(self) -> str:
        return str(self._required_state()["llm"].get("api_key", ""))

    def set_secret(self, handle: str, value: str) -> None:
        state = self._required_state()
        state["secrets"][str(handle)] = str(value)
        self._persist_encrypted()

    def get_secret(self, handle: str) -> str:
        state = self._required_state()
        if handle not in state["secrets"]:
            raise KeyError(handle)
        return str(state["secrets"][handle])

    def get_identity_state(self) -> dict[str, Any]:
        state = self._required_state()["identity"]
        return {
            "llm_allowed_telegram_user_ids": [int(v) for v in state.get("llm_allowed_telegram_user_ids", [])],
            "gate_bindings": {str(k): str(v) for k, v in dict(state.get("gate_bindings", {})).items()},
            "trusted_gate_user_ids": [int(v) for v in state.get("trusted_gate_user_ids", [])],
        }

    def save_identity_state(self, identity_state: dict[str, Any]) -> None:
        state = self._required_state()
        current = self.get_identity_state()
        current["llm_allowed_telegram_user_ids"] = [int(v) for v in identity_state.get("llm_allowed_telegram_user_ids", [])]
        current["gate_bindings"] = {str(k): str(v) for k, v in dict(identity_state.get("gate_bindings", {})).items()}
        if "trusted_gate_user_ids" in identity_state:
            current["trusted_gate_user_ids"] = [int(v) for v in identity_state.get("trusted_gate_user_ids", [])]
        state["identity"] = current
        self._persist_encrypted()
        if self.telegram_secrets_path.exists():
            cfg = json.loads(self.telegram_secrets_path.read_text(encoding="utf-8"))
            cfg["trusted_gate_user_ids"] = current["trusted_gate_user_ids"]
            self.telegram_secrets_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    def add_trusted_gate_user(self, user_id: int) -> None:
        identity = self.get_identity_state()
        trusted = set(identity["trusted_gate_user_ids"])
        trusted.add(int(user_id))
        identity["trusted_gate_user_ids"] = sorted(trusted)
        self.save_identity_state(identity)

    def trusted_gate_users(self) -> set[int]:
        if self.telegram_secrets_path.exists():
            cfg = json.loads(self.telegram_secrets_path.read_text(encoding="utf-8"))
            return {int(v) for v in cfg.get("trusted_gate_user_ids", [])}
        return set(self.get_identity_state().get("trusted_gate_user_ids", []))

    def _required_state(self) -> dict[str, Any]:
        if self._state is None:
            raise SecretsServiceLockedError("secrets service is locked")
        return self._state

    def _persist_encrypted(self) -> None:
        if self._state is None or self._password is None:
            raise SecretsServiceLockedError("secrets service is locked")
        self.encrypted_path.write_bytes(encrypt_blob(self._state, self._password))

    def _normalize_state(self, data: dict[str, Any]) -> dict[str, Any]:
        llm = data.get("llm", {}) if isinstance(data, dict) else {}
        gate = data.get("gate", {}) if isinstance(data, dict) else {}
        identity = data.get("identity", {}) if isinstance(data, dict) else {}
        return {
            "version": int(data.get("version", 1)) if isinstance(data, dict) else 1,
            "llm": {
                "provider": str(llm.get("provider", "openai")),
                "api_key": str(llm.get("api_key", "")),
                "telegram_bot_token": str(llm.get("telegram_bot_token", "")),
            },
            "gate": {
                "telegram_bot_token": str(gate.get("telegram_bot_token", "")),
                "allow_telegram_master_password": bool(gate.get("allow_telegram_master_password", False)),
            },
            "identity": {
                "llm_allowed_telegram_user_ids": [int(v) for v in identity.get("llm_allowed_telegram_user_ids", [])],
                "gate_bindings": {str(k): str(v) for k, v in dict(identity.get("gate_bindings", {})).items()},
                "trusted_gate_user_ids": [int(v) for v in identity.get("trusted_gate_user_ids", [])],
            },
            "secrets": {str(k): str(v) for k, v in dict(data.get("secrets", {})).items()} if isinstance(data, dict) else {},
        }
