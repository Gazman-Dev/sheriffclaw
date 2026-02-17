import json
import pytest
from shared.secrets_state import SecretsState

def test_secrets_initialize_and_verify(tmp_path):
    enc_path = tmp_path / "secrets.enc"
    ver_path = tmp_path / "master.json"
    state = SecretsState(enc_path, ver_path)

    state.initialize({"master_password": "correct-horse"})

    assert state.verify_master_password("correct-horse")
    assert not state.verify_master_password("wrong")
    assert enc_path.exists()

def test_secrets_encryption_roundtrip(tmp_path):
    enc_path = tmp_path / "secrets.enc"
    ver_path = tmp_path / "master.json"

    # Init
    s1 = SecretsState(enc_path, ver_path)
    s1.initialize({"master_password": "pw", "llm_api_key": "key-123"})
    s1.unlock("pw")
    s1.set_secret("gh", "token")

    # Reload
    s2 = SecretsState(enc_path, ver_path)
    assert not s2.is_unlocked()

    # Wrong password
    s2.unlock("wrong")
    assert not s2.is_unlocked()

    # Correct password
    s2.unlock("pw")
    assert s2.is_unlocked()
    assert s2.get_llm_api_key() == "key-123"
    assert s2.get_secret("gh") == "token"

def test_locking_clears_memory(tmp_path):
    state = SecretsState(tmp_path / "s.enc", tmp_path / "m.json")
    state.initialize({"master_password": "pw"})
    state.unlock("pw")
    state.set_secret("k", "v")

    state.lock()
    assert not state.is_unlocked()

    with pytest.raises(RuntimeError, match="locked"):
        state.get_secret("k")

def test_ensure_handle(tmp_path):
    state = SecretsState(tmp_path / "s.enc", tmp_path / "m.json")
    state.initialize({"master_password": "pw"})
    state.unlock("pw")

    assert not state.ensure_handle("missing")
    state.set_secret("exists", "val")
    assert state.ensure_handle("exists")