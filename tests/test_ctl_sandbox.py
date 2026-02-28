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
    assert "sandbox-exec" not in cmd[0]
