import json

import pytest

from python_openclaw.gateway.credentials import CredentialStore, CredentialStoreLockedError
from python_openclaw.gateway.identity_store import IdentityStore
from python_openclaw.gateway.master_password import create_verifier, verify_password
from python_openclaw.gateway.unlock_server import UnlockCoordinator, UnlockDependencies


def test_credential_store_encrypt_decrypt(tmp_path):
    store = CredentialStore(tmp_path / "credentials.json", tmp_path / "credentials.enc", mode="encrypted")
    creds = {
        "telegram": {"agent_token": "123:ABC", "gate_token": "456:DEF"},
        "llm": {"openai_api_key": "sk-test", "anthropic_api_key": "", "google_api_key": "", "moonshot_api_key": ""},
    }
    store.set_initial(creds, master_password="pw")
    raw = (tmp_path / "credentials.enc").read_bytes()
    assert b"123:ABC" not in raw and b"sk-test" not in raw

    store.lock()
    with pytest.raises(CredentialStoreLockedError):
        store.get_telegram_tokens()

    store.unlock("pw")
    assert store.get_telegram_tokens() == ("123:ABC", "456:DEF")


def test_master_verifier_accepts_correct_password():
    verifier = create_verifier("correct horse battery staple")
    assert verify_password("correct horse battery staple", verifier)
    assert not verify_password("wrong", verifier)


def test_identity_store_persistence(tmp_path):
    store = IdentityStore(tmp_path / "identity.json", tmp_path / "identity.enc", mode="plaintext")
    state = {"llm_allowed_telegram_user_ids": [100], "gate_bindings": {"tg:100": "tg:dm:100"}}
    store.persist_unlocked(state, master_password="")
    loaded = store.load()
    assert loaded["llm_allowed_telegram_user_ids"] == [100]
    assert loaded["gate_bindings"]["tg:100"] == "tg:dm:100"


def test_unlock_coordinator_transitions_locked_runtime(tmp_path):
    password = "pw"
    verifier = create_verifier(password)

    states = {"secrets": False, "credentials": False, "identity": False}

    def unlock_cb(candidate: str) -> None:
        assert candidate == password
        states["secrets"] = True
        states["credentials"] = True
        states["identity"] = True

    coordinator = UnlockCoordinator(UnlockDependencies(verify_record=verifier, unlock_callback=unlock_cb))
    assert coordinator.attempt_unlock("bad")["error"] == "wrong_password"
    assert not all(states.values())

    result = coordinator.attempt_unlock(password)
    assert result == {"status": "ok"}
    assert all(states.values())
