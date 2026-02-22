from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from shared.proc_rpc import ProcClient


class SheriffUpdaterService:
    def __init__(self) -> None:
        self.secrets = ProcClient("sheriff-secrets")

    async def run_update(self, payload, emit_event, req_id):
        master_password = payload.get("master_password") or ""
        auto_pull = bool(payload.get("auto_pull", True))

        if not master_password:
            return {"ok": False, "error": "master_password_required"}

        _, res = await self.secrets.request("secrets.verify_master_password", {"master_password": master_password})
        if not res.get("result", {}).get("ok"):
            return {"ok": False, "error": "invalid_master_password"}

        repo_root = Path(__file__).resolve().parents[2]

        if not auto_pull:
            return {"ok": True, "mode": "restart_only"}

        if auto_pull and (repo_root / ".git").exists():
            subprocess.run(["git", "-C", str(repo_root), "pull", "--ff-only"], check=False)  # noqa: S603

        pip_cmd = [sys.executable, "-m", "pip", "install", "-q", str(repo_root)]
        proc = subprocess.run(pip_cmd, check=False)  # noqa: S603
        if proc.returncode != 0:
            return {"ok": False, "error": "pip_install_failed", "code": proc.returncode}

        return {"ok": True, "mode": "full_update"}

    def ops(self):
        return {
            "updater.run": self.run_update,
        }
