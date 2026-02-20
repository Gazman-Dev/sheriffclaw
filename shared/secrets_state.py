from __future__ import annotations

import hashlib
import json
from pathlib import Path

from shared.crypto import decrypt_text, encrypt_text


class SecretsState:
    def __init__(self, enc_path: Path, verifier_path: Path):
        self.enc_path = enc_path
        self.verifier_path = verifier_path
        self._password: str | None = None
        self._state: dict = {}

    @staticmethod
    def _hash(password: str) -> str:
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    def initialize(self, payload: dict) -> None:
        password = payload["master_password"]
        state = {
            "llm_provider": payload.get("llm_provider", "stub"),
            "llm_api_key": payload.get("llm_api_key", ""),
            "llm_bot_token": payload.get("llm_bot_token", ""),
            "gate_bot_token": payload.get("gate_bot_token", ""),
            "allow_telegram_master_password": bool(payload.get("allow_telegram_master_password", False)),
            "secrets": {},
            "identity": {"allowed_ids": [], "gate_bindings": {}},
        }
        self.verifier_path.parent.mkdir(parents=True, exist_ok=True)
        self.verifier_path.write_text(json.dumps({"hash": self._hash(password)}), encoding="utf-8")
        self.enc_path.write_text(encrypt_text(json.dumps(state), password), encoding="utf-8")

    def verify_master_password(self, password: str) -> bool:
        if not self.verifier_path.exists():
            return False
        data = json.loads(self.verifier_path.read_text(encoding="utf-8"))
        return data.get("hash") == self._hash(password)

    def unlock(self, password: str) -> bool:
        if not self.verify_master_password(password):
            return False
        if self.enc_path.exists():
            self._state = json.loads(decrypt_text(self.enc_path.read_text(encoding="utf-8"), password))
        self._password = password
        return True

    def lock(self) -> None:
        self._password = None
        self._state = {}

    def is_unlocked(self) -> bool:
        return self._password is not None

    def _require(self) -> None:
        if not self._password:
            raise RuntimeError("secrets are locked")

    def _persist(self) -> None:
        self._require()
        self.enc_path.parent.mkdir(parents=True, exist_ok=True)
        self.enc_path.write_text(encrypt_text(json.dumps(self._state), self._password or ""), encoding="utf-8")

    def get_secret(self, handle: str) -> str | None:
        self._require()
        return self._state.get("secrets", {}).get(handle)

    def set_secret(self, handle: str, value: str) -> None:
        self._require()
        self._state.setdefault("secrets", {})[handle] = value
        self._persist()

    def ensure_handle(self, handle: str) -> bool:
        self._require()
        return handle in self._state.get("secrets", {})

    def get_llm_provider(self) -> str:
        self._require()
        return self._state.get("llm_provider", "stub")

    def get_llm_api_key(self) -> str:
        self._require()
        return self._state.get("llm_api_key", "")

    def set_llm_provider(self, provider: str) -> None:
        self._require()
        self._state["llm_provider"] = provider
        self._persist()

    def set_llm_api_key(self, api_key: str) -> None:
        self._require()
        self._state["llm_api_key"] = api_key
        self._persist()

    def get_llm_bot_token(self) -> str:
        self._require()
        return self._state.get("llm_bot_token", "")

    def get_gate_bot_token(self) -> str:
        self._require()
        return self._state.get("gate_bot_token", "")

    def get_identity(self) -> dict:
        self._require()
        return self._state.get("identity", {"allowed_ids": [], "gate_bindings": {}})

    def save_identity(self, identity: dict) -> None:
        self._require()
        self._state["identity"] = identity
        self._persist()
