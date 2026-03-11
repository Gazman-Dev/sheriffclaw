from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from shared.component_versions import diff_versions, load_applied_versions, load_target_versions, save_applied_versions
from shared.paths import base_root


class SheriffUpdaterService:
    def __init__(self) -> None:
        install_root = base_root().resolve()
        file_root = Path(__file__).resolve().parents[2]
        cwd_root = Path.cwd().resolve()
        source_root = (install_root / "source").resolve()
        if (source_root / "versions.json").exists():
            self.repo_root = source_root
        elif (file_root / "versions.json").exists():
            self.repo_root = file_root
        elif (cwd_root / "versions.json").exists():
            self.repo_root = cwd_root
        else:
            self.repo_root = file_root

    def _build_plan(self, *, force: bool = False) -> dict:
        target_versions = load_target_versions(self.repo_root)
        applied_versions = load_applied_versions()
        changes = diff_versions(target_versions, applied_versions)
        return {
            "target_versions": target_versions,
            "applied_versions": applied_versions,
            "changes": changes,
            "should_update": True,
            "needs_master_password": False,
            "force": force,
        }

    async def plan_update(self, payload, emit_event, req_id):
        return self._build_plan(force=bool(payload.get("force", False)))

    async def run_update(self, payload, emit_event, req_id):
        auto_pull = bool(payload.get("auto_pull", True))
        force = bool(payload.get("force", False))

        if auto_pull and (self.repo_root / ".git").exists():
            git_res = subprocess.run(
                ["git", "-C", str(self.repo_root), "pull", "--ff-only"],
                check=False,
                capture_output=True,
                text=True,
            )  # noqa: S603
            if git_res.returncode != 0:
                return {
                    "ok": False,
                    "error": "git_pull_failed",
                    "code": git_res.returncode,
                    "stderr": (git_res.stderr or "").strip(),
                }

        plan = self._build_plan(force=force)

        # Force reinstall so removed/renamed package files from previous versions are cleaned up.
        pip_cmd =[
            sys.executable,
            "-m",
            "pip",
            "install",
            "-q",
            "--upgrade",
            "--force-reinstall",
            str(self.repo_root),
        ]
        proc = subprocess.run(pip_cmd, check=False, capture_output=True, text=True)  # noqa: S603
        if proc.returncode != 0:
            return {
                "ok": False,
                "error": "pip_install_failed",
                "code": proc.returncode,
                "stderr": (proc.stderr or "").strip(),
                "stdout": (proc.stdout or "").strip(),
                "plan": plan,
            }

        save_applied_versions(plan["target_versions"])
        return {"ok": True, "mode": "full_update", "plan": plan}

    def ops(self):
        return {
            "updater.plan": self.plan_update,
            "updater.run": self.run_update,
        }
