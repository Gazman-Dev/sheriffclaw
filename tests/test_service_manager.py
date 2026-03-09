from __future__ import annotations

from pathlib import Path
import subprocess

from shared.service_manager import ServiceManager


def _mgr(tmp_path, monkeypatch, runs):
    def _run(cmd, check=False, capture_output=False, text=False):
        runs.append(list(cmd))

        class R:
            returncode = 1
            stdout = ""

        return R()

    monkeypatch.setattr("shared.service_manager.subprocess.run", _run)
    return ServiceManager(
        lambda service: ["python", service],
        lambda service: tmp_path / f"{service}.pid",
        lambda service: (tmp_path / f"{service}.out", tmp_path / f"{service}.err"),
    )


def test_ai_worker_stop_kills_stale_children(tmp_path, monkeypatch):
    runs = []
    mgr = ServiceManager(
        lambda service: ["sudo", "-n", "-u", "sheriffai", "/usr/local/bin/sheriff-codex-mcp-host-launch"] if service == "codex-mcp-host" else ["python", service],
        lambda service: tmp_path / f"{service}.pid",
        lambda service: (tmp_path / f"{service}.out", tmp_path / f"{service}.err"),
    )
    status_calls = {"count": 0}

    def _run(cmd, check=False, capture_output=False, text=False):
        runs.append(list(cmd))
        if cmd[-1] == "status":
            status_calls["count"] += 1
            if status_calls["count"] == 1:
                return type("R", (), {"returncode": 0, "stdout": "456\n"})()
        return type("R", (), {"returncode": 1, "stdout": ""})()

    monkeypatch.setattr("shared.service_manager.subprocess.run", _run)
    pidfile = tmp_path / "codex-mcp-host.pid"
    pidfile.write_text("123", encoding="utf-8")
    monkeypatch.setattr(mgr, "alive", lambda pid: False)
    monkeypatch.setattr("shared.service_manager.os.kill", lambda pid, sig: None)

    mgr.stop("codex-mcp-host")

    assert ["sudo", "-n", "-u", "sheriffai", "/usr/local/bin/sheriff-codex-mcp-host-launch", "stop"] in runs
    assert ["sudo", "-n", "-u", "sheriffai", "/usr/local/bin/sheriff-codex-mcp-host-launch", "status"] in runs
    assert ["pkill", "-f", "/bin/codex-mcp-host"] not in runs
    assert ["pkill", "-f", " codex-mcp-host"] not in runs


def test_ai_worker_stop_forces_kill_when_launcher_stop_does_not_clear_processes(tmp_path, monkeypatch):
    runs = []
    mgr = ServiceManager(
        lambda service: ["sudo", "-n", "-u", "sheriffai", "/usr/local/bin/sheriff-codex-mcp-host-launch"] if service == "codex-mcp-host" else ["python", service],
        lambda service: tmp_path / f"{service}.pid",
        lambda service: (tmp_path / f"{service}.out", tmp_path / f"{service}.err"),
    )

    def _run(cmd, check=False, capture_output=False, text=False):
        runs.append(list(cmd))
        if cmd[-1] == "status":
            return type("R", (), {"returncode": 0, "stdout": "456\n"})()
        return type("R", (), {"returncode": 1, "stdout": ""})()

    pidfile = tmp_path / "codex-mcp-host.pid"
    pidfile.write_text("123", encoding="utf-8")
    monkeypatch.setattr("shared.service_manager.subprocess.run", _run)
    monkeypatch.setattr(mgr, "alive", lambda pid: False)
    monkeypatch.setattr("shared.service_manager.os.kill", lambda pid, sig: None)
    monkeypatch.setattr("shared.service_manager.time.sleep", lambda _: None)

    mgr.stop("codex-mcp-host")

    assert ["pkill", "-f", "services.ai_worker.__main__"] in runs
    assert ["pkill", "-f", "sheriff-codex-mcp-host-launch"] in runs
    assert ["pkill", "-f", "codex mcp-server"] in runs


def test_ai_worker_status_uses_process_probe_when_pid_dead(tmp_path, monkeypatch):
    runs = []

    def _run(cmd, check=False, capture_output=False, text=False):
        runs.append(list(cmd))

        class R:
            returncode = 0 if cmd[-1] == "status" else 0
            stdout = "99999\n"

        return R()

    monkeypatch.setattr("shared.service_manager.subprocess.run", _run)
    mgr = ServiceManager(
        lambda service: ["sudo", "-n", "-u", "sheriffai", "/usr/local/bin/sheriff-codex-mcp-host-launch"] if service == "codex-mcp-host" else ["python", service],
        lambda service: tmp_path / f"{service}.pid",
        lambda service: (tmp_path / f"{service}.out", tmp_path / f"{service}.err"),
    )
    monkeypatch.setattr(mgr, "alive", lambda pid: False)

    assert mgr.status_code("codex-mcp-host") == "99999"
    assert ["sudo", "-n", "-u", "sheriffai", "/usr/local/bin/sheriff-codex-mcp-host-launch", "status"] in runs


def test_alive_treats_permission_error_as_running(monkeypatch):
    def _raise(pid, sig):
        raise PermissionError(1, "operation not permitted")

    monkeypatch.setattr("shared.service_manager.os.kill", _raise)

    assert ServiceManager.alive(12345) is True


def test_start_detaches_service_stdin(tmp_path, monkeypatch):
    captured = {}

    class P:
        pid = 123

    def _popen(cmd, stdin=None, stdout=None, stderr=None, env=None):
        captured["cmd"] = list(cmd)
        captured["stdin"] = stdin
        captured["stdout"] = stdout
        captured["stderr"] = stderr
        captured["env"] = env
        return P()

    monkeypatch.setattr("shared.service_manager.subprocess.Popen", _popen)
    monkeypatch.setattr("shared.service_manager.subprocess.run", lambda *args, **kwargs: type("R", (), {"returncode": 1, "stdout": ""})())

    mgr = ServiceManager(
        lambda service: ["python", service],
        lambda service: tmp_path / f"{service}.pid",
        lambda service: (tmp_path / f"{service}.out", tmp_path / f"{service}.err"),
    )

    assert mgr.start("svc") == "started"
    assert captured["stdin"] is subprocess.DEVNULL
    assert (tmp_path / "svc.pid").read_text(encoding="utf-8") == "123"
