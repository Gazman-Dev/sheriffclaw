from __future__ import annotations

from pathlib import Path

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
    mgr = _mgr(tmp_path, monkeypatch, runs)
    pidfile = tmp_path / "ai-worker.pid"
    pidfile.write_text("123", encoding="utf-8")
    monkeypatch.setattr(mgr, "alive", lambda pid: False)
    monkeypatch.setattr("shared.service_manager.os.kill", lambda pid, sig: None)

    mgr.stop("ai-worker")

    assert ["pkill", "-f", "services.ai_worker.__main__"] in runs
    assert ["pkill", "-f", "sheriff-ai-worker-launch"] in runs


def test_ai_worker_status_uses_process_probe_when_pid_dead(tmp_path, monkeypatch):
    runs = []

    def _run(cmd, check=False, capture_output=False, text=False):
        runs.append(list(cmd))

        class R:
            returncode = 0
            stdout = "99999\n"

        return R()

    monkeypatch.setattr("shared.service_manager.subprocess.run", _run)
    mgr = ServiceManager(
        lambda service: ["python", service],
        lambda service: tmp_path / f"{service}.pid",
        lambda service: (tmp_path / f"{service}.out", tmp_path / f"{service}.err"),
    )
    monkeypatch.setattr(mgr, "alive", lambda pid: False)

    assert mgr.status_code("ai-worker") == "running"
    assert ["pgrep", "-f", "services.ai_worker.__main__"] in runs
