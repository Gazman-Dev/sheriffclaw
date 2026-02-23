from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path


class ServiceManager:
    def __init__(
        self,
        command_for: Callable[[str], list[str]],
        pid_path_for: Callable[[str], Path],
        log_paths_for: Callable[[str], tuple[Path, Path]],
    ) -> None:
        self._command_for = command_for
        self._pid_path_for = pid_path_for
        self._log_paths_for = log_paths_for

    def read_pid(self, service: str) -> int | None:
        p = self._pid_path_for(service)
        if not p.exists():
            return None
        try:
            return int(p.read_text(encoding="utf-8").strip())
        except ValueError:
            return None

    @staticmethod
    def alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False

    def status_code(self, service: str) -> str:
        pid = self.read_pid(service)
        if pid and self.alive(pid):
            return str(pid)
        return "stopped"

    def _kill_by_name_fallback(self, service: str) -> None:
        # Cleanup stale processes that may survive pidfile churn (best-effort).
        subprocess.run(["pkill", "-f", f"/bin/{service}"], check=False)  # noqa: S603
        subprocess.run(["pkill", "-f", f" {service}"], check=False)  # noqa: S603

    def start(self, service: str) -> str:
        pid = self.read_pid(service)
        if pid and self.alive(pid):
            return "already_running"
        # Avoid duplicate lingering workers after update/reinstall.
        self._kill_by_name_fallback(service)
        out_path, err_path = self._log_paths_for(service)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        err_path.parent.mkdir(parents=True, exist_ok=True)
        out = out_path.open("a", encoding="utf-8")
        err = err_path.open("a", encoding="utf-8")
        proc = subprocess.Popen(self._command_for(service), stdout=out, stderr=err)  # noqa: S603
        self._pid_path_for(service).write_text(str(proc.pid), encoding="utf-8")
        return "started"

    def stop(self, service: str) -> str:
        pid = self.read_pid(service)
        if pid is None:
            self._kill_by_name_fallback(service)
            return "already_stopped"
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            self._pid_path_for(service).unlink(missing_ok=True)
            return "already_stopped"

        deadline = time.time() + 3
        while time.time() < deadline and self.alive(pid):
            time.sleep(0.1)
        if self.alive(pid):
            os.kill(pid, signal.SIGKILL)
        self._pid_path_for(service).unlink(missing_ok=True)
        return "stopped"

    def start_many(self, services: list[str]) -> dict[str, str]:
        return {svc: self.start(svc) for svc in services}

    def stop_many(self, services: list[str]) -> dict[str, str]:
        return {svc: self.stop(svc) for svc in services}
