from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import string
from pathlib import Path

from shared.crypto import decrypt_text, encrypt_text


class SecretsState:
    def __init__(self, enc_path: Path, verifier_path: Path):
        # enc_path now stores sqlite DB (extension kept for backward compatibility)
        self.db_path = enc_path
        self.verifier_path = verifier_path
        self._password: str | None = None

    @staticmethod
    def _hash(password: str) -> str:
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    @staticmethod
    def _key_hash(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @staticmethod
    def _default_state(payload: dict) -> dict:
        return {
            "llm_provider": payload.get("llm_provider", "stub"),
            "llm_api_key": payload.get("llm_api_key", ""),
            "llm_bot_token": payload.get("llm_bot_token", ""),
            "gate_bot_token": payload.get("gate_bot_token", ""),
            "llm_auth": {
                "type": None,
                "access_token": None,
                "refresh_token": None,
                "id_token": None,
                "obtained_at": None,
                "expires_at": None,
            },
            "allow_telegram_master_password": bool(payload.get("allow_telegram_master_password", False)),
            "telegram_webhook": None,
            "secrets": {},
            "identity": {
                "allowed_ids": [],
                "gate_bindings": {},
                "bot_bindings": {"llm": None, "sheriff": None},
                "pending_activation": {"llm": {}, "sheriff": {}},
            },
        }

    def _db_connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv (
              key_hash TEXT PRIMARY KEY,
              key_enc TEXT NOT NULL,
              value_enc TEXT NOT NULL,
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        return conn

    def _db_set(self, key: str, value) -> None:
        self._require()
        assert self._password is not None
        k_enc = encrypt_text(key, self._password)
        v_enc = encrypt_text(json.dumps(value), self._password)
        with self._db_connect() as conn:
            conn.execute(
                """
                INSERT INTO kv(key_hash, key_enc, value_enc, updated_at)
                VALUES(?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(key_hash) DO UPDATE SET
                  key_enc=excluded.key_enc,
                  value_enc=excluded.value_enc,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (self._key_hash(key), k_enc, v_enc),
            )
            conn.commit()

    def _db_get(self, key: str, default=None):
        self._require()
        assert self._password is not None
        with self._db_connect() as conn:
            row = conn.execute("SELECT value_enc FROM kv WHERE key_hash=?", (self._key_hash(key),)).fetchone()
        if not row:
            return default
        try:
            raw = decrypt_text(str(row[0]), self._password)
            return json.loads(raw)
        except Exception:
            return default

    def _db_all(self) -> dict:
        self._require()
        assert self._password is not None
        out = {}
        with self._db_connect() as conn:
            rows = conn.execute("SELECT key_enc, value_enc FROM kv").fetchall()
        for k_enc, v_enc in rows:
            try:
                k = decrypt_text(str(k_enc), self._password)
                v = json.loads(decrypt_text(str(v_enc), self._password))
                out[k] = v
            except Exception:
                continue
        return out

    def _is_sqlite(self) -> bool:
        if not self.db_path.exists():
            return False
        try:
            head = self.db_path.read_bytes()[:16]
            return head.startswith(b"SQLite format 3")
        except Exception:
            return False

    def _migrate_legacy_if_needed(self, password: str) -> None:
        if not self.db_path.exists() or self._is_sqlite():
            return
        # legacy single encrypted blob json
        try:
            legacy = json.loads(decrypt_text(self.db_path.read_text(encoding="utf-8"), password))
        except Exception:
            legacy = {}
        with self._db_connect() as conn:
            conn.execute("DELETE FROM kv")
            conn.commit()
        self._password = password
        for k, v in legacy.items():
            self._db_set(k, v)

    def initialize(self, payload: dict) -> None:
        password = payload["master_password"]
        state = self._default_state(payload)
        self.verifier_path.parent.mkdir(parents=True, exist_ok=True)
        self.verifier_path.write_text(json.dumps({"hash": self._hash(password)}), encoding="utf-8")

        # fresh sqlite init
        if self.db_path.exists() and not self._is_sqlite():
            self.db_path.unlink(missing_ok=True)
        with self._db_connect() as conn:
            conn.execute("DELETE FROM kv")
            conn.commit()

        self._password = password
        for k, v in state.items():
            self._db_set(k, v)
        self._password = None

    def verify_master_password(self, password: str) -> bool:
        if not self.verifier_path.exists():
            return False
        data = json.loads(self.verifier_path.read_text(encoding="utf-8"))
        return data.get("hash") == self._hash(password)

    def unlock(self, password: str) -> bool:
        if not self.verify_master_password(password):
            return False
        self._migrate_legacy_if_needed(password)
        if not self.db_path.exists():
            # initialize empty schema
            with self._db_connect() as conn:
                conn.commit()
        self._password = password
        return True

    def lock(self) -> None:
        self._password = None

    def is_unlocked(self) -> bool:
        return self._password is not None

    def _require(self) -> None:
        if not self._password:
            raise RuntimeError("secrets are locked")

    # generic config helpers
    def get_config(self, key: str, default=None):
        return self._db_get(key, default)

    def set_config(self, key: str, value) -> None:
        self._db_set(key, value)

    # typed helpers used by services
    def get_secret(self, handle: str) -> str | None:
        secrets = self._db_get("secrets", {})
        return secrets.get(handle)

    def set_secret(self, handle: str, value: str) -> None:
        secrets = self._db_get("secrets", {})
        secrets[handle] = value
        self._db_set("secrets", secrets)

    def ensure_handle(self, handle: str) -> bool:
        secrets = self._db_get("secrets", {})
        return handle in secrets

    def get_llm_provider(self) -> str:
        return str(self._db_get("llm_provider", "stub"))

    def get_llm_api_key(self) -> str:
        return str(self._db_get("llm_api_key", ""))

    def set_llm_provider(self, provider: str) -> None:
        self._db_set("llm_provider", provider)

    def set_llm_api_key(self, api_key: str) -> None:
        self._db_set("llm_api_key", api_key)

    def get_llm_auth(self) -> dict:
        return self._db_get("llm_auth", {"type": None, "access_token": None, "refresh_token": None, "expires_at": None})

    def set_llm_auth(self, auth: dict) -> None:
        self._db_set(
            "llm_auth",
            {
                "type": auth.get("type"),
                "access_token": auth.get("access_token"),
                "refresh_token": auth.get("refresh_token"),
                "id_token": auth.get("id_token"),
                "obtained_at": auth.get("obtained_at"),
                "expires_at": auth.get("expires_at"),
            },
        )

    def clear_llm_auth(self) -> None:
        self._db_set("llm_auth", {"type": None, "access_token": None, "refresh_token": None, "id_token": None, "obtained_at": None, "expires_at": None})

    def get_llm_bot_token(self) -> str:
        return str(self._db_get("llm_bot_token", ""))

    def set_llm_bot_token(self, token: str) -> None:
        self._db_set("llm_bot_token", token)

    def get_gate_bot_token(self) -> str:
        return str(self._db_get("gate_bot_token", ""))

    def set_gate_bot_token(self, token: str) -> None:
        self._db_set("gate_bot_token", token)

    def get_identity(self) -> dict:
        return self._db_get("identity", {"allowed_ids": [], "gate_bindings": {}})

    def save_identity(self, identity: dict) -> None:
        self._db_set("identity", identity)

    def _ensure_identity_shape(self) -> dict:
        ident = self.get_identity() or {}
        ident.setdefault("allowed_ids", [])
        ident.setdefault("gate_bindings", {})
        ident.setdefault("bot_bindings", {"llm": None, "sheriff": None})
        ident.setdefault("pending_activation", {"llm": {}, "sheriff": {}})
        return ident

    def create_activation_code(self, bot_role: str, user_id: str) -> str:
        ident = self._ensure_identity_shape()
        pending = ident["pending_activation"].setdefault(bot_role, {})
        alphabet = string.ascii_uppercase + string.digits
        code = "".join(random.choice(alphabet) for _ in range(6))
        pending[code] = str(user_id)
        self.save_identity(ident)
        return code

    def activate_with_code(self, bot_role: str, code: str) -> str | None:
        ident = self._ensure_identity_shape()
        pending = ident["pending_activation"].setdefault(bot_role, {})
        user_id = pending.pop(code, None)
        if user_id is None:
            return None
        ident["bot_bindings"][bot_role] = str(user_id)
        if str(user_id) not in ident["allowed_ids"]:
            ident["allowed_ids"].append(str(user_id))
        self.save_identity(ident)
        return str(user_id)

    def get_bound_user(self, bot_role: str) -> str | None:
        ident = self._ensure_identity_shape()
        return ident.get("bot_bindings", {}).get(bot_role)

    def is_user_allowed_for_bot(self, bot_role: str, user_id: str) -> bool:
        ident = self._ensure_identity_shape()
        return ident.get("bot_bindings", {}).get(bot_role) == str(user_id)

    def get_telegram_webhook_config(self) -> dict | None:
        return self._db_get("telegram_webhook", None)

    def set_telegram_webhook_config(self, cfg: dict) -> None:
        self._db_set("telegram_webhook", cfg)
