import pytest
from unittest.mock import MagicMock
from services.sheriff_secrets.service import SheriffSecretsService
from shared.paths import gw_root

@pytest.fixture
def mock_paths(tmp_path, monkeypatch):
    # Redirect gw_root to a temp dir so state/secrets.enc writes there
    monkeypatch.setattr("services.sheriff_secrets.service.gw_root", lambda: tmp_path)
    return tmp_path

@pytest.mark.asyncio
async def test_secrets_service_flow(mock_paths):
    svc = SheriffSecretsService()

    # 1. Initialize
    await svc.initialize({
        "master_password": "super-secret",
        "llm_api_key": "sk-123"
    }, None, "req-1")

    # 2. Verify Locked initially (or after init, state might need explicit unlock depending on logic,
    # but based on code, init writes disk but doesn't auto-set self._password usually, let's check unlock)
    resp = await svc.is_unlocked({}, None, "req-2")
    assert resp["unlocked"] is False

    # 3. Unlock
    unlock_resp = await svc.unlock({"master_password": "super-secret"}, None, "req-3")
    assert unlock_resp["ok"] is True

    # 4. Get Data
    key_resp = await svc.get_llm_api_key({}, None, "req-4")
    assert key_resp["api_key"] == "sk-123"

    # 5. Set/Get Secret
    await svc.set_secret({"handle": "gh", "value": "token"}, None, "req-5")
    secret_resp = await svc.get_secret({"handle": "gh"}, None, "req-6")
    assert secret_resp["value"] == "token"

@pytest.mark.asyncio
async def test_secrets_lock(mock_paths):
    svc = SheriffSecretsService()
    await svc.initialize({"master_password": "pw"}, None, "r1")
    await svc.unlock({"master_password": "pw"}, None, "r2")

    assert (await svc.is_unlocked({}, None, "r3"))["unlocked"] is True

    await svc.lock({}, None, "r4")
    assert (await svc.is_unlocked({}, None, "r5"))["unlocked"] is False

    with pytest.raises(RuntimeError):
        await svc.get_llm_api_key({}, None, "r6")