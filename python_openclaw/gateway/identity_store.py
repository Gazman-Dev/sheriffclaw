from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from python_openclaw.gateway.secrets.crypto import decrypt_blob, encrypt_blob


class IdentityStoreLockedError(RuntimeError):
    pass


class IdentityStore:
    def __init__(self, path_plain: Path, path_enc: Path, mode: str = "plaintext") -> None:
        self.path_plain = path_plain
        self.path_enc = path_enc
        self.mode = mode
        self._state: dict[str, Any] | None = None
        self.path_plain.parent.mkdir(parents=True, exist_ok=True)

    def is_encrypted_mode(self) -> bool:
        return self.mode == "encrypted"

    @property
    def unlocked(self) -> bool:
        if not self.is_encrypted_mode():
            return True
        return self._state is not None

    def unlock(self, master_password: str) -> None:
        if not self.is_encrypted_mode():
            return
        if not self.path_enc.exists() or self.path_enc.stat().st_size == 0:
            self._state = {"llm_allowed_telegram_user_ids": [], "gate_bindings": {}}
            return
        self._state = _normalize_identity(decrypt_blob(self.path_enc.read_bytes(), master_password))

    def load(self) -> dict[str, Any]:
        if self.is_encrypted_mode():
            if self._state is None:
                raise IdentityStoreLockedError("identity store locked")
            return self._state
        if not self.path_plain.exists():
            return {"llm_allowed_telegram_user_ids": [], "gate_bindings": {}}
        return _normalize_identity(json.loads(self.path_plain.read_text(encoding="utf-8")))

    def save(self, state: dict[str, Any], master_password: str | None = None) -> None:
        normalized = _normalize_identity(state)
        if self.is_encrypted_mode():
            if self._state is None and not master_password:
                raise IdentityStoreLockedError("identity store locked")
            if master_password:
                self.path_enc.write_bytes(encrypt_blob(normalized, master_password))
            else:
                raise IdentityStoreLockedError("master_password required for encrypted save")
            self._state = normalized
            return
        self.path_plain.write_text(json.dumps(normalized, indent=2), encoding="utf-8")

    def persist_unlocked(self, state: dict[str, Any], master_password: str) -> None:
        normalized = _normalize_identity(state)
        if self.is_encrypted_mode():
            self.path_enc.write_bytes(encrypt_blob(normalized, master_password))
            self._state = normalized
            return
        self.path_plain.write_text(json.dumps(normalized, indent=2), encoding="utf-8")


def _normalize_identity(data: dict[str, Any]) -> dict[str, Any]:
    allowed = data.get("llm_allowed_telegram_user_ids", []) if isinstance(data, dict) else []
    gate = data.get("gate_bindings", {}) if isinstance(data, dict) else {}
    return {
        "llm_allowed_telegram_user_ids": [int(v) for v in allowed],
        "gate_bindings": {str(k): str(v) for k, v in dict(gate).items()},
    }
