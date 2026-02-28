import json
import pytest
from shared.secrets_state import SecretsState

def test_secrets_initialize_and_verify(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFF_DEBUG", "0")
    enc_path = tmp_path / "secrets.enc"
    ver_path = tmp_path / "master.json"
    state = SecretsState(enc_path, ver_path)

    state.initialize({"master_password": "correct-horse"})

    assert state.verify_master_password("correct-horse")
    assert not state.verify_master_password("wrong")
    assert enc_path.exists()

def test_secrets_encryption_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFF_DEBUG", "0")
    enc_path = tmp_path / "secrets.enc"
    ver_path = tmp_path / "master.json"

    # Init
    s1 = SecretsState(enc_path, ver_path)
    s1.initialize({"master_password": "pw", "llm_api_key": "key-123"})
    s1.unlock("pw")
    s1.set_secret("gh", "token")

    # Reload should restore unlocked session for process consistency
    s2 = SecretsState(enc_path, ver_path)
    assert s2.is_unlocked()

    # Lock then wrong password remains locked
    s2.lock()
    s2.unlock("wrong")
    assert not s2.is_unlocked()

    # Correct password
    s2.unlock("pw")
    assert s2.is_unlocked()
    assert s2.get_llm_api_key() == "key-123"
    assert s2.get_secret("gh") == "token"

def test_locking_clears_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFF_DEBUG", "0")
    state = SecretsState(tmp_path / "s.enc", tmp_path / "m.json")
    state.initialize({"master_password": "pw"})
    state.unlock("pw")
    state.set_secret("k", "v")

    state.lock()
    assert not state.is_unlocked()

    with pytest.raises(RuntimeError, match="locked"):
        state.get_secret("k")

def test_ensure_handle(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFF_DEBUG", "0")
    state = SecretsState(tmp_path / "s.enc", tmp_path / "m.json")
    state.initialize({"master_password": "pw"})
    state.unlock("pw")

    assert not state.ensure_handle("missing")
    state.set_secret("exists", "val")
    assert state.ensure_handle("exists")


def test_debug_mode_uses_isolated_files_and_forced_password(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFF_DEBUG", "1")
    state = SecretsState(tmp_path / "secrets.db", tmp_path / "master.json")
    state.initialize({"master_password": "not-used", "llm_api_key": "super-secret"})

    assert state.db_path.name == "secrets.debug.db"
    assert state.verifier_path.name == "master.debug.json"
    assert state.verify_master_password("debug") is True
    assert state.verify_master_password("not-used") is False
    assert state.unlock("debug") is True
    assert state.get_llm_api_key() != "super-secret"
