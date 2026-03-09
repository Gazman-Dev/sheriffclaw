# File: tests/test_ctl_sandbox.py

from pathlib import Path

from services.sheriff_ctl import sandbox, service_runner


def test_service_command_codex_mcp_host_sandbox_on_darwin(monkeypatch, tmp_path):
    monkeypatch.setattr(service_runner.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service_runner.shutil, "which", lambda x: "/usr/bin/sandbox-exec")
    monkeypatch.setattr(sandbox, "gw_root", lambda: tmp_path / "gw")
    monkeypatch.setattr(sandbox, "llm_root", lambda: tmp_path / "llm")
    monkeypatch.setattr(sandbox.sys, "platform", "darwin")
    monkeypatch.setattr(sandbox, "_darwin_sandbox_profile_path", lambda: tmp_path / "shared" / "ai_worker.sb")
    launcher = tmp_path / "usr" / "local" / "bin" / "sheriff-codex-mcp-host-launch"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/bin/bash\n", encoding="utf-8")
    monkeypatch.setattr(service_runner, "_darwin_ai_worker_launcher_path", lambda: launcher)
    monkeypatch.setattr(service_runner, "_ai_worker_user", lambda: "")

    cmd = service_runner._service_command("codex-mcp-host")
    assert cmd[0].endswith("sandbox-exec")
    assert cmd[1] == "-f"
    assert Path(cmd[2]).exists()
    assert Path(cmd[2]) == tmp_path / "shared" / "ai_worker.sb"


def test_codex_mcp_host_sandbox_profile_on_darwin_uses_shared_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "gw_root", lambda: tmp_path / "gw")
    monkeypatch.setattr(sandbox, "llm_root", lambda: tmp_path / "llm")
    monkeypatch.setattr(sandbox.sys, "platform", "darwin")
    monkeypatch.setattr(sandbox, "_darwin_sandbox_profile_path", lambda: tmp_path / "shared" / "ai_worker.sb")
    monkeypatch.setattr(sandbox, "_ai_worker_user", lambda: "sheriffai")
    monkeypatch.setattr(sandbox, "_darwin_ai_worker_runtime_root", lambda: tmp_path / "runtime")

    path = sandbox._ai_worker_sandbox_profile()
    text = path.read_text(encoding="utf-8")

    assert path == tmp_path / "shared" / "ai_worker.sb"
    assert path.exists()
    assert "(allow default)" in text
    assert str(tmp_path / "runtime") in text


def test_codex_mcp_host_sandbox_profile_allows_real_python_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "gw_root", lambda: tmp_path / "gw")
    monkeypatch.setattr(sandbox, "llm_root", lambda: tmp_path / "llm")
    monkeypatch.setattr(sandbox.sys, "platform", "darwin")
    monkeypatch.setattr(sandbox, "_darwin_sandbox_profile_path", lambda: tmp_path / "shared" / "ai_worker.sb")
    monkeypatch.setattr(sandbox, "_darwin_ai_worker_runtime_root", lambda: tmp_path / "runtime")

    path = sandbox._ai_worker_sandbox_profile()
    text = path.read_text(encoding="utf-8")

    assert str(tmp_path / "runtime") in text


def test_service_command_linux_bwrap(monkeypatch, tmp_path):
    monkeypatch.setattr(service_runner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(service_runner.shutil, "which", lambda x: "/usr/bin/bwrap" if x == "bwrap" else None)
    monkeypatch.setattr(sandbox, "gw_root", lambda: tmp_path / "gw")
    monkeypatch.setattr(sandbox, "llm_root", lambda: tmp_path / "llm")

    cmd = service_runner._service_command("codex-mcp-host")
    assert cmd[0].endswith("bwrap")


def test_service_command_strict_missing_runtime_raises(monkeypatch):
    monkeypatch.setattr(service_runner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(service_runner.shutil, "which", lambda x: None)
    monkeypatch.setenv("SHERIFF_STRICT_SANDBOX", "1")
    try:
        service_runner._service_command("codex-mcp-host")
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_service_command_non_host_plain(monkeypatch):
    monkeypatch.setattr(service_runner.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service_runner.shutil, "which", lambda x: "/usr/bin/sandbox-exec")
    cmd = service_runner._service_command("sheriff-gateway")
    assert cmd[0].endswith("python") or cmd[0].endswith("python.exe")


def test_service_command_codex_mcp_host_missing_user_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(service_runner.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service_runner.shutil, "which", lambda x: "/usr/bin/sandbox-exec" if x == "sandbox-exec" else "/usr/bin/sudo")
    monkeypatch.setattr(sandbox, "gw_root", lambda: tmp_path / "gw")
    monkeypatch.setattr(sandbox, "llm_root", lambda: tmp_path / "llm")
    monkeypatch.setattr(service_runner, "_ai_worker_user", lambda: "sheriffai")
    monkeypatch.setattr(service_runner, "_posix_user_exists", lambda user: False)
    monkeypatch.setattr(service_runner, "_darwin_ai_worker_launcher_path", lambda: tmp_path / "launcher")

    try:
        service_runner._service_command("codex-mcp-host")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "does not exist" in str(exc)


def test_service_command_codex_mcp_host_darwin_requires_launcher_for_dedicated_user(monkeypatch, tmp_path):
    monkeypatch.setattr(service_runner.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service_runner.shutil, "which", lambda x: "/usr/bin/sandbox-exec" if x == "sandbox-exec" else "/usr/bin/sudo")
    monkeypatch.setattr(sandbox, "gw_root", lambda: tmp_path / "gw")
    monkeypatch.setattr(sandbox, "llm_root", lambda: tmp_path / "llm")
    monkeypatch.setattr(service_runner, "_ai_worker_user", lambda: "sheriffai")
    monkeypatch.setattr(service_runner, "_posix_user_exists", lambda user: True)
    monkeypatch.setattr(service_runner, "_darwin_ai_worker_launcher_path", lambda: tmp_path / "missing-launcher")

    try:
        service_runner._service_command("codex-mcp-host")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "missing macOS codex-mcp-host launcher" in str(exc)


def test_service_command_codex_mcp_host_darwin_uses_launcher_for_dedicated_user(monkeypatch, tmp_path):
    monkeypatch.setattr(service_runner.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service_runner.shutil, "which", lambda x: "/usr/bin/sandbox-exec" if x == "sandbox-exec" else "/usr/bin/sudo")
    monkeypatch.setattr(sandbox, "gw_root", lambda: tmp_path / "gw")
    monkeypatch.setattr(sandbox, "llm_root", lambda: tmp_path / "llm")
    monkeypatch.setattr(service_runner, "_ai_worker_user", lambda: "sheriffai")
    monkeypatch.setattr(service_runner, "_posix_user_exists", lambda user: True)
    launcher = tmp_path / "usr" / "local" / "bin" / "sheriff-codex-mcp-host-launch"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/bin/bash\n", encoding="utf-8")
    monkeypatch.setattr(service_runner, "_darwin_ai_worker_launcher_path", lambda: launcher)

    cmd = service_runner._service_command("codex-mcp-host")

    assert cmd[:4] == ["/usr/bin/sudo", "-n", "-u", "sheriffai"]
    assert cmd[4] == str(launcher)


def test_service_command_codex_mcp_host_requires_sudo_for_dedicated_user(monkeypatch, tmp_path):
    monkeypatch.setattr(service_runner.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service_runner.shutil, "which", lambda x: "/usr/bin/sandbox-exec" if x == "sandbox-exec" else None)
    monkeypatch.setattr(sandbox, "gw_root", lambda: tmp_path / "gw")
    monkeypatch.setattr(sandbox, "llm_root", lambda: tmp_path / "llm")
    monkeypatch.setattr(service_runner, "_ai_worker_user", lambda: "sheriffai")
    monkeypatch.setattr(service_runner, "_posix_user_exists", lambda user: True)
    launcher = tmp_path / "usr" / "local" / "bin" / "sheriff-codex-mcp-host-launch"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/bin/bash\n", encoding="utf-8")
    monkeypatch.setattr(service_runner, "_darwin_ai_worker_launcher_path", lambda: launcher)

    try:
        service_runner._service_command("codex-mcp-host")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "sudo is required" in str(exc)
