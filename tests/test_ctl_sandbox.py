# File: tests/test_ctl_sandbox.py

from pathlib import Path

from services.sheriff_ctl import sandbox, service_runner


def test_service_command_ai_worker_sandbox_on_darwin(monkeypatch, tmp_path):
    monkeypatch.setattr(service_runner.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service_runner.shutil, "which", lambda x: "/usr/bin/sandbox-exec")
    monkeypatch.setattr(sandbox, "gw_root", lambda: tmp_path / "gw")
    monkeypatch.setattr(sandbox, "llm_root", lambda: tmp_path / "llm")

    cmd = service_runner._service_command("ai-worker")
    assert cmd[0].endswith("sandbox-exec")
    assert cmd[1] == "-f"
    assert Path(cmd[2]).exists()


def test_service_command_linux_bwrap(monkeypatch, tmp_path):
    monkeypatch.setattr(service_runner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(service_runner.shutil, "which", lambda x: "/usr/bin/bwrap" if x == "bwrap" else None)
    monkeypatch.setattr(sandbox, "gw_root", lambda: tmp_path / "gw")
    monkeypatch.setattr(sandbox, "llm_root", lambda: tmp_path / "llm")

    cmd = service_runner._service_command("ai-worker")
    assert cmd[0].endswith("bwrap")


def test_service_command_strict_missing_runtime_raises(monkeypatch):
    monkeypatch.setattr(service_runner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(service_runner.shutil, "which", lambda x: None)
    monkeypatch.setenv("SHERIFF_STRICT_SANDBOX", "1")
    try:
        service_runner._service_command("ai-worker")
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_service_command_non_ai_worker_plain(monkeypatch):
    monkeypatch.setattr(service_runner.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service_runner.shutil, "which", lambda x: "/usr/bin/sandbox-exec")
    cmd = service_runner._service_command("sheriff-gateway")
    assert cmd[0].endswith("python") or cmd[0].endswith("python.exe")


def test_service_command_ai_worker_missing_user_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(service_runner.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service_runner.shutil, "which", lambda x: "/usr/bin/sandbox-exec" if x == "sandbox-exec" else "/usr/bin/sudo")
    monkeypatch.setattr(sandbox, "gw_root", lambda: tmp_path / "gw")
    monkeypatch.setattr(sandbox, "llm_root", lambda: tmp_path / "llm")
    monkeypatch.setattr(service_runner, "_ai_worker_user", lambda: "sheriffai")
    monkeypatch.setattr(service_runner, "_posix_user_exists", lambda user: False)

    try:
        service_runner._service_command("ai-worker")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "does not exist" in str(exc)


def test_service_command_ai_worker_requires_sudo_for_dedicated_user(monkeypatch, tmp_path):
    monkeypatch.setattr(service_runner.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service_runner.shutil, "which", lambda x: "/usr/bin/sandbox-exec" if x == "sandbox-exec" else None)
    monkeypatch.setattr(sandbox, "gw_root", lambda: tmp_path / "gw")
    monkeypatch.setattr(sandbox, "llm_root", lambda: tmp_path / "llm")
    monkeypatch.setattr(service_runner, "_ai_worker_user", lambda: "sheriffai")
    monkeypatch.setattr(service_runner, "_posix_user_exists", lambda user: True)

    try:
        service_runner._service_command("ai-worker")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "sudo is required" in str(exc)
