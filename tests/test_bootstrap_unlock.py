import json

from python_openclaw.gateway.master_password import create_verifier, verify_password
from python_openclaw.gateway.secrets.service import SecretsService, SecretsServiceLockedError


def test_master_verifier_accepts_correct_password():
    verifier = create_verifier("correct horse battery staple")
    assert verify_password("correct horse battery staple", verifier)
    assert not verify_password("wrong", verifier)


def test_secrets_service_encrypts_and_unlocks(tmp_path):
    service = SecretsService(
        encrypted_path=tmp_path / "secrets_service.enc",
        master_verifier_path=tmp_path / "master.json",
        telegram_secrets_path=tmp_path / "telegram_secrets_channel.json",
    )
    service.initialize(
        master_password="pw",
        provider="openai",
        llm_api_key="sk-test",
        llm_bot_token="123:ABC",
        gate_bot_token="456:DEF",
        allow_telegram_master_password=False,
    )
    raw = (tmp_path / "secrets_service.enc").read_bytes()
    assert b"sk-test" not in raw and b"123:ABC" not in raw

    service.lock()
    try:
        service.get_llm_bot_token()
        raise AssertionError("expected locked error")
    except SecretsServiceLockedError:
        pass

    assert service.verify_master_password("pw")
    service.unlock("pw")
    assert service.get_gate_bot_token() == "456:DEF"


def test_plaintext_gate_config_when_telegram_master_password_enabled(tmp_path):
    service = SecretsService(
        encrypted_path=tmp_path / "secrets_service.enc",
        master_verifier_path=tmp_path / "master.json",
        telegram_secrets_path=tmp_path / "telegram_secrets_channel.json",
    )
    service.initialize(
        master_password="pw",
        provider="openai",
        llm_api_key="sk-test",
        llm_bot_token="123:ABC",
        gate_bot_token="456:DEF",
        allow_telegram_master_password=True,
    )
    plaintext = json.loads((tmp_path / "telegram_secrets_channel.json").read_text(encoding="utf-8"))
    assert plaintext["telegram_bot_token"] == "456:DEF"
    assert service.gate_channel_uses_plaintext_config()
