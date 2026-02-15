from pathlib import Path

import pytest

from python_openclaw.gateway.secrets.crypto import SecretCryptoError
from python_openclaw.gateway.secrets.store import SecretLockedError, SecretStore


def test_secrets_encrypt_decrypt_and_no_plaintext(tmp_path: Path):
    store = SecretStore(tmp_path / "secrets.enc")
    store.unlock("pass123")
    store.set_secret("github", "topsecret-token")
    raw = (tmp_path / "secrets.enc").read_bytes()
    assert b"topsecret-token" not in raw

    reloaded = SecretStore(tmp_path / "secrets.enc")
    reloaded.unlock("pass123")
    assert reloaded.get_secret("github") == "topsecret-token"


def test_wrong_passphrase_fails(tmp_path: Path):
    store = SecretStore(tmp_path / "secrets.enc")
    store.unlock("correct")
    store.set_secret("github", "abc")

    with pytest.raises(SecretCryptoError):
        SecretStore(tmp_path / "secrets.enc").unlock("wrong")


def test_lock_unlock_lifecycle(tmp_path: Path):
    store = SecretStore(tmp_path / "secrets.enc")
    with pytest.raises(SecretLockedError):
        store.set_secret("k", "v")

    store.unlock("pw")
    store.set_secret("k", "v")
    assert store.get_secret("k") == "v"

    store.lock()
    with pytest.raises(SecretLockedError):
        store.get_secret("k")
