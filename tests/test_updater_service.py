import pytest

from services.sheriff_updater.service import SheriffUpdaterService


def _pip_install_calls(calls):
    return [c for c in calls if len(c) >= 4 and c[1:4] == ["-m", "pip", "install"]]


def test_updater_prefers_install_root_source_from_env(monkeypatch, tmp_path):
    install_root = tmp_path / "install"
    source_root = install_root / "source"
    source_root.mkdir(parents=True)
    (source_root / "versions.json").write_text('{"agent":"1.0.0","sheriff":"1.0.0","secrets":"1.0.0"}\n', encoding="utf-8")
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(install_root))

    svc = SheriffUpdaterService()

    assert svc.repo_root == source_root.resolve()


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

    calls =[]

    def fake_run(cmd, check=False, capture_output=False, text=False):
        calls.append(cmd)

        class P:
            returncode = 0
            stdout = ""
            stderr = ""

        return P()

    monkeypatch.setattr("services.sheriff_updater.service.subprocess.run", fake_run)

    svc = SheriffUpdaterService()
    svc.repo_root = repo

    out = await svc.run_update({"auto_pull": False}, None, "r1")
    assert out["ok"] is True
    assert out["mode"] == "full_update"
    pip_calls = _pip_install_calls(calls)
    assert len(pip_calls) == 1
    assert "--upgrade" in pip_calls[0]


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

    calls =[]

    def fake_run(cmd, check=False, capture_output=False, text=False):
        calls.append(cmd)

        class P:
            returncode = 0
            stdout = ""
            stderr = ""

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
async def test_updater_does_not_require_master_password_when_secrets_version_increased(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "versions.json").write_text('{"agent":"1.0.0","sheriff":"1.0.0","secrets":"1.0.1"}\n', encoding="utf-8")

    monkeypatch.setattr("services.sheriff_updater.service.load_applied_versions",
                        lambda: {"agent": "1.0.0", "sheriff": "1.0.0", "secrets": "1.0.0"})

    calls = []

    def fake_run(cmd, check=False, capture_output=False, text=False):
        calls.append(cmd)

        class P:
            returncode = 0
            stdout = ""
            stderr = ""

        return P()

    monkeypatch.setattr("services.sheriff_updater.service.subprocess.run", fake_run)
    saved = {}

    def fake_save(v):
        saved.update(v)

    monkeypatch.setattr("services.sheriff_updater.service.save_applied_versions", fake_save)

    svc = SheriffUpdaterService()
    svc.repo_root = repo

    out = await svc.run_update({"auto_pull": False}, None, "r3")
    assert out["ok"] is True
    assert out["mode"] == "full_update"
    pip_calls = _pip_install_calls(calls)
    assert len(pip_calls) == 1
    assert saved == {"agent": "1.0.0", "sheriff": "1.0.0", "secrets": "1.0.1"}


@pytest.mark.asyncio
async def test_updater_does_not_require_master_password_when_only_non_secrets_increased(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "versions.json").write_text('{"agent":"1.0.1","sheriff":"1.0.0","secrets":"1.0.0"}\n', encoding="utf-8")

    monkeypatch.setattr("services.sheriff_updater.service.load_applied_versions",
                        lambda: {"agent": "1.0.0", "sheriff": "1.0.0", "secrets": "1.0.0"})

    calls =[]

    def fake_run(cmd, check=False, capture_output=False, text=False):
        calls.append(cmd)

        class P:
            returncode = 0
            stdout = ""
            stderr = ""

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

    calls =[]

    def fake_run(cmd, check=False, capture_output=False, text=False):
        calls.append(cmd)

        class P:
            returncode = 17
            stdout = "pip stdout"
            stderr = "pip stderr"

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
    assert out["stderr"] == "pip stderr"
    assert out["stdout"] == "pip stdout"


@pytest.mark.asyncio
async def test_updater_returns_error_when_git_pull_fails(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "versions.json").write_text('{"agent":"1.0.1","sheriff":"1.0.0","secrets":"1.0.0"}\n', encoding="utf-8")

    monkeypatch.setattr(
        "services.sheriff_updater.service.load_applied_versions",
        lambda: {"agent": "1.0.0", "sheriff": "1.0.0", "secrets": "1.0.0"},
    )

    calls = []

    def fake_run(cmd, check=False, capture_output=False, text=False):
        calls.append((cmd, capture_output, text))

        class P:
            if cmd[0] == "git":
                returncode = 9
                stdout = ""
                stderr = "git failed"
            else:
                returncode = 0
                stdout = ""
                stderr = ""

        return P()

    monkeypatch.setattr("services.sheriff_updater.service.subprocess.run", fake_run)
    monkeypatch.setattr("services.sheriff_updater.service.save_applied_versions", lambda _: None)

    svc = SheriffUpdaterService()
    svc.repo_root = repo

    out = await svc.run_update({"auto_pull": True}, None, "r6")
    assert out["ok"] is False
    assert out["error"] == "git_pull_failed"
    assert out["code"] == 9
    assert out["stderr"] == "git failed"
    assert calls[0][1] is True
    assert calls[0][2] is True
