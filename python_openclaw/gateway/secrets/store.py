from __future__ import annotations

from pathlib import Path

from python_openclaw.gateway.secrets.crypto import SecretCryptoError, decrypt_blob, encrypt_blob


class SecretLockedError(Exception):
    pass


class SecretStore:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._secrets: dict[str, str] | None = None
        self._passphrase: str | None = None

    @property
    def unlocked(self) -> bool:
        return self._secrets is not None

    def unlock(self, passphrase: str) -> None:
        if self.file_path.exists() and self.file_path.stat().st_size > 0:
            self._secrets = decrypt_blob(self.file_path.read_bytes(), passphrase)
        else:
            self._secrets = {}
        self._passphrase = passphrase

    def lock(self) -> None:
        self._secrets = None
        self._passphrase = None

    def set_secret(self, handle: str, value: str) -> None:
        if self._secrets is None or self._passphrase is None:
            raise SecretLockedError("secret store locked")
        self._secrets[handle] = value
        self._persist()

    def ensure_handle(self, handle: str) -> bool:
        if self._secrets is None:
            raise SecretLockedError("secret store locked")
        return handle in self._secrets

    def get_secret(self, handle: str) -> str:
        if self._secrets is None:
            raise SecretLockedError("secret store locked")
        if handle not in self._secrets:
            raise KeyError(handle)
        return self._secrets[handle]

    def _persist(self) -> None:
        assert self._secrets is not None and self._passphrase is not None
        self.file_path.write_bytes(encrypt_blob(self._secrets, self._passphrase))
