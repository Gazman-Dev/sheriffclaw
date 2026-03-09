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
            env_for: Callable[[str], dict[str, str]] | None = None,
    ) -> None:
        self._command_for = command_for
        self._pid_path_for = pid_path_for
        self._log_paths_for = log_paths_for
        self._env_for = env_for or (lambda _service: os.environ.copy())

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
        except PermissionError:
            # Another OS user owns the process; treat it as running.
            return True

    def status_code(self, service: str) -> str:
        pid = self.read_pid(service)
        if pid and self.alive(pid):
            return str(pid)
        if service == "codex-mcp-host":
            ctl_cmd = self._host_launcher_control_cmd("status")
            if ctl_cmd is not None:
                probe = subprocess.run(
                    ctl_cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if probe.returncode == 0 and (probe.stdout or "").strip():
                    return (probe.stdout or "").strip()
            probe = subprocess.run(
                ["pgrep", "-f", "services.ai_worker.__main__"],
                check=False,
                capture_output=True,
                text=True,
            )
            if probe.returncode == 0 and (probe.stdout or "").strip():
                return "running"
        return "stopped"

    def _host_launcher_control_cmd(self, action: str) -> list[str] | None:
        start_cmd = self._command_for("codex-mcp-host")
        if len(start_cmd) >= 5 and start_cmd[:3] == ["sudo", "-n", "-u"]:
            launcher = start_cmd[4]
            if launcher.endswith("sheriff-codex-mcp-host-launch"):
                return [*start_cmd[:5], action]
        return None

    def _launcher_reports_running(self) -> bool:
        ctl_cmd = self._host_launcher_control_cmd("status")
        if ctl_cmd is None:
            return False
        probe = subprocess.run(
            ctl_cmd,
            check=False,
            capture_output=True,
            text=True,
        )
        return probe.returncode == 0 and bool((probe.stdout or "").strip())

    def _wait_host_stopped(self, timeout_sec: float = 5.0) -> bool:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if not self._launcher_reports_running():
                return True
            time.sleep(0.2)
        return not self._launcher_reports_running()

    def _service_match_patterns(self, service: str) -> list[str]:
        cmd = self._command_for(service)
        patterns = {f"/bin/{service}", f" {service}"}
        if len(cmd) >= 3 and cmd[1] == "-m":
            patterns.add(str(cmd[2]))
        elif cmd:
            patterns.add(str(Path(cmd[0]).name))
        return [pattern for pattern in patterns if pattern]

    def _kill_by_name_fallback(self, service: str) -> None:
        # Cleanup stale processes that may survive pidfile churn (best-effort).
        if service == "codex-mcp-host":
            ctl_cmd = self._host_launcher_control_cmd("stop")
            if ctl_cmd is not None:
                subprocess.run(ctl_cmd, check=False)  # noqa: S603
                if self._wait_host_stopped():
                    return
            subprocess.run(["pkill", "-f", "services.ai_worker.__main__"], check=False)  # noqa: S603
            subprocess.run(["pkill", "-f", "sheriff-codex-mcp-host-launch"], check=False)  # noqa: S603
            subprocess.run(["pkill", "-f", "codex mcp-server"], check=False)  # noqa: S603
            return
        for pattern in self._service_match_patterns(service):
            subprocess.run(["pkill", "-f", pattern], check=False)  # noqa: S603

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
        proc = subprocess.Popen(
            self._command_for(service),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            env=self._env_for(service),
        )  # noqa: S603
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
        self._kill_by_name_fallback(service)
        if service == "codex-mcp-host":
            self._wait_host_stopped()
        self._pid_path_for(service).unlink(missing_ok=True)
        return "stopped"

    def start_many(self, services: list[str]) -> dict[str, str]:
        return {svc: self.start(svc) for svc in services}

    def stop_many(self, services: list[str]) -> dict[str, str]:
        return {svc: self.stop(svc) for svc in services}
