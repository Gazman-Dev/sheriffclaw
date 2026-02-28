import pytest

from services.sheriff_updater.service import SheriffUpdaterService


def _pip_install_calls(calls):
    return [c for c in calls if len(c) >= 4 and c[1:4] == ["-m", "pip", "install"]]


@pytest.mark.asyncio
async def test_updater_skips_when_versions_not_increased(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "versions.json").write_text('{"agent":"1.0.0","sheriff":"1.0.0","secrets":"1.0.0"}\n', encoding="utf-8")

    monkeypatch.setattr("services.sheriff_updater.service.load_applied_versions",
                        lambda: {"agent": "1.0.0", "sheriff": "1.0.0", "secrets": "1.0.0"})

    saved = {}

    def fake_save(v):
        saved.update(v)

    monkeypatch.setattr("services.sheriff_updater.service.save_applied_versions", fake_save)

    calls = []

    def fake_run(cmd, check=False):
        calls.append(cmd)

        class P:
            returncode = 0

        return P()

    monkeypatch.setattr("services.sheriff_updater.service.subprocess.run", fake_run)

    svc = SheriffUpdaterService()
    svc.repo_root = repo

    out = await svc.run_update({"auto_pull": False}, None, "r1")
    assert out["ok"] is True
    assert out["mode"] == "skipped"
    assert out["reason"] == "version_not_increased"
    assert calls == []
    assert saved == {}


@pytest.mark.asyncio
async def test_updater_force_updates_even_without_version_increase(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "versions.json").write_text('{"agent":"1.0.0","sheriff":"1.0.0","secrets":"1.0.0"}\n', encoding="utf-8")

    monkeypatch.setattr("services.sheriff_updater.service.load_applied_versions",
                        lambda: {"agent": "1.0.0", "sheriff": "1.0.0", "secrets": "1.0.0"})

    saved = {}

    def fake_save(v):
        saved.update(v)

    monkeypatch.setattr("services.sheriff_updater.service.save_applied_versions", fake_save)

    calls = []

    def fake_run(cmd, check=False):
        calls.append(cmd)

        class P:
            returncode = 0

        return P()

    monkeypatch.setattr("services.sheriff_updater.service.subprocess.run", fake_run)

    svc = SheriffUpdaterService()
    svc.repo_root = repo

    out = await svc.run_update({"auto_pull": False, "force": True}, None, "r2")
    assert out["ok"] is True
    assert out["mode"] == "full_update"
    pip_calls = _pip_install_calls(calls)
    assert len(pip_calls) == 1
    assert "--upgrade" in pip_calls[0]
    assert "--force-reinstall" in pip_calls[0]
    assert str(repo) in pip_calls[0]
    assert saved == {"agent": "1.0.0", "sheriff": "1.0.0", "secrets": "1.0.0"}


@pytest.mark.asyncio
async def test_updater_requires_master_password_when_secrets_version_increased(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "versions.json").write_text('{"agent":"1.0.0","sheriff":"1.0.0","secrets":"1.0.1"}\n', encoding="utf-8")

    monkeypatch.setattr("services.sheriff_updater.service.load_applied_versions",
                        lambda: {"agent": "1.0.0", "sheriff": "1.0.0", "secrets": "1.0.0"})

    def fake_run(cmd, check=False):
        class P:
            returncode = 0

        return P()

    monkeypatch.setattr("services.sheriff_updater.service.subprocess.run", fake_run)

    svc = SheriffUpdaterService()
    svc.repo_root = repo

    out = await svc.run_update({"auto_pull": False}, None, "r3")
    assert out["ok"] is False
    assert out["error"] == "master_password_required"


@pytest.mark.asyncio
async def test_updater_does_not_require_master_password_when_only_non_secrets_increased(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "versions.json").write_text('{"agent":"1.0.1","sheriff":"1.0.0","secrets":"1.0.0"}\n', encoding="utf-8")

    monkeypatch.setattr("services.sheriff_updater.service.load_applied_versions",
                        lambda: {"agent": "1.0.0", "sheriff": "1.0.0", "secrets": "1.0.0"})

    calls = []

    def fake_run(cmd, check=False):
        calls.append(cmd)

        class P:
            returncode = 0

        return P()

    monkeypatch.setattr("services.sheriff_updater.service.subprocess.run", fake_run)

    saved = {}

    def fake_save(v):
        saved.update(v)

    monkeypatch.setattr("services.sheriff_updater.service.save_applied_versions", fake_save)

    svc = SheriffUpdaterService()
    svc.repo_root = repo

    out = await svc.run_update({"auto_pull": False}, None, "r4")
    assert out["ok"] is True
    assert out["mode"] == "full_update"
    pip_calls = _pip_install_calls(calls)
    assert len(pip_calls) == 1
    assert "--upgrade" in pip_calls[0]
    assert "--force-reinstall" in pip_calls[0]
    assert str(repo) in pip_calls[0]
    assert saved == {"agent": "1.0.1", "sheriff": "1.0.0", "secrets": "1.0.0"}


@pytest.mark.asyncio
async def test_updater_returns_error_when_reinstall_fails(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "versions.json").write_text('{"agent":"1.0.1","sheriff":"1.0.0","secrets":"1.0.0"}\n', encoding="utf-8")

    monkeypatch.setattr(
        "services.sheriff_updater.service.load_applied_versions",
        lambda: {"agent": "1.0.0", "sheriff": "1.0.0", "secrets": "1.0.0"},
    )

    calls = []

    def fake_run(cmd, check=False):
        calls.append(cmd)

        class P:
            returncode = 17

        return P()

    monkeypatch.setattr("services.sheriff_updater.service.subprocess.run", fake_run)
    monkeypatch.setattr("services.sheriff_updater.service.save_applied_versions", lambda _: None)

    svc = SheriffUpdaterService()
    svc.repo_root = repo

    out = await svc.run_update({"auto_pull": False}, None, "r5")
    assert out["ok"] is False
    assert out["error"] == "pip_install_failed"
    assert out["code"] == 17
    pip_calls = _pip_install_calls(calls)
    assert len(pip_calls) == 1
    assert "--upgrade" in pip_calls[0]
    assert "--force-reinstall" in pip_calls[0]
    assert str(repo) in pip_calls[0]
