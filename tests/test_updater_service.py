import pytest
from unittest.mock import AsyncMock

from services.sheriff_updater.service import SheriffUpdaterService


@pytest.mark.asyncio
async def test_updater_rejects_missing_password(monkeypatch):
    svc = SheriffUpdaterService()
    out = await svc.run_update({}, None, "r1")
    assert out["ok"] is False


@pytest.mark.asyncio
async def test_updater_rejects_invalid_password(monkeypatch):
    svc = SheriffUpdaterService()
    svc.secrets = AsyncMock()
    svc.secrets.request.return_value = (None, {"result": {"ok": False}})

    out = await svc.run_update({"master_password": "bad", "auto_pull": False}, None, "r1")
    assert out["ok"] is False
    assert out["error"] == "invalid_master_password"


@pytest.mark.asyncio
async def test_updater_restart_only_mode(monkeypatch):
    svc = SheriffUpdaterService()
    svc.secrets = AsyncMock()
    svc.secrets.request.return_value = (None, {"result": {"ok": True}})

    out = await svc.run_update({"master_password": "ok", "auto_pull": False}, None, "r1")
    assert out["ok"] is True
    assert out["mode"] == "restart_only"


@pytest.mark.asyncio
async def test_updater_full_update_mode(monkeypatch):
    svc = SheriffUpdaterService()
    svc.secrets = AsyncMock()
    svc.secrets.request.return_value = (None, {"result": {"ok": True}})

    calls = []

    class P:
        returncode = 0

    def fake_run(cmd, check=False):
        calls.append(cmd)
        return P()

    monkeypatch.setattr("services.sheriff_updater.service.subprocess.run", fake_run)

    out = await svc.run_update({"master_password": "ok", "auto_pull": True}, None, "r1")
    assert out["ok"] is True
    assert any("pip" in " ".join(c) for c in calls)
