# File: services/sheriff_ctl/service_runner.py

from __future__ import annotations

import asyncio
import os
import platform
import shutil

from services.sheriff_ctl.sandbox import (
    _ai_worker_sandbox_profile,
    _ai_worker_user,
    _linux_sandbox_profile,
    _strict_sandbox_required,
)
from services.sheriff_ctl.utils import (
    _gw_secrets_call,
    _log_paths,
    _notify_sheriff_channel,
    _pid_path,
    _resolve_service_binary,
)
from shared.proc_rpc import ProcClient
from shared.service_manager import ServiceManager

GW_ORDER = [
    "sheriff-secrets",
    "sheriff-policy",
    "sheriff-requests",
    "sheriff-web",
    "sheriff-tools",
    "sheriff-gateway",
    "sheriff-tg-gate",
    "sheriff-cli-gate",
    "sheriff-updater",
]
LLM_ORDER = ["ai-worker", "ai-tg-llm", "telegram-listener"]
ALL = [*GW_ORDER, *LLM_ORDER]

# Daemonized services managed directly by ServiceManager.
# Keep secrets always-on so unlock state survives normal operation.
MANAGED_SERVICES = ["sheriff-secrets", "telegram-listener"]


def _service_command(service: str) -> list[str]:
    base = [_resolve_service_binary(service)]
    if service == "ai-worker":
        sandboxed = None
        if platform.system() == "Darwin":
            sb = shutil.which("sandbox-exec")
            if sb:
                profile = _ai_worker_sandbox_profile()
                sandboxed = [sb, "-f", str(profile), *base]
        elif platform.system() == "Linux":
            bwrap = shutil.which("bwrap")
            if bwrap:
                profile = _linux_sandbox_profile()
                args = [ln.strip() for ln in profile.read_text(encoding="utf-8").splitlines() if ln.strip()]
                sandboxed = [bwrap, *args, *base]

        if sandboxed is None:
            if _strict_sandbox_required():
                raise RuntimeError(
                    "strict sandbox enabled: ai-worker sandbox runtime missing (need sandbox-exec or bwrap)")
            sandboxed = base

        user = _ai_worker_user()
        if user and platform.system() in {"Darwin", "Linux"}:
            sudo = shutil.which("sudo")
            if sudo:
                sandboxed = [sudo, "-n", "-u", user, *sandboxed]

        return sandboxed
    return base


SERVICE_MANAGER = ServiceManager(_service_command, _pid_path, _log_paths)


def _start_service(service: str) -> None:
    SERVICE_MANAGER.start(service)


def _read_pid(service: str) -> int | None:
    return SERVICE_MANAGER.read_pid(service)


def _alive(pid: int) -> bool:
    return SERVICE_MANAGER.alive(pid)


def _stop_service(service: str) -> None:
    SERVICE_MANAGER.stop(service)


def cmd_start(args):
    mp = getattr(args, "master_password", None) or os.getenv("SHERIFF_MASTER_PASSWORD", "")

    # Avoid resetting secrets lock state unless we can unlock immediately.
    to_restart = list(MANAGED_SERVICES)
    if not mp and "sheriff-secrets" in to_restart:
        pid = _read_pid("sheriff-secrets")
        if pid and _alive(pid):
            to_restart = [svc for svc in to_restart if svc != "sheriff-secrets"]

    # Restart managed services we selected to avoid stale old binaries.
    SERVICE_MANAGER.stop_many(list(reversed(to_restart)))
    SERVICE_MANAGER.start_many(to_restart)

    if mp:
        async def _unlock():
            gw = ProcClient("sheriff-gateway")
            for _ in range(10):
                try:
                    await gw.request("health", {})
                    break
                except Exception:
                    await asyncio.sleep(0.2)
            res = await _gw_secrets_call("secrets.unlock", {"master_password": mp})
            return bool(res.get("ok"))

        ok = asyncio.run(_unlock())
        if ok:
            print("Vault unlocked on start.")
            _notify_sheriff_channel("✅ Sheriff services restarted and vault unlocked.")
        else:
            print("Warning: failed to unlock vault on start (master password rejected).")
            _notify_sheriff_channel("🔒 Sheriff restarted but vault is locked. Send: /unlock <master_password>")
    else:
        _notify_sheriff_channel(
            "ℹ️ Sheriff services restarted. Vault state unknown; send /unlock <master_password> if needed.")


def cmd_stop(args):
    SERVICE_MANAGER.stop_many(list(reversed(MANAGED_SERVICES)))


def cmd_status(args):
    for svc in ALL:
        print(f"{svc}: {SERVICE_MANAGER.status_code(svc)}")


def cmd_logs(args):
    out, err = _log_paths(args.service)
    if out.exists():
        print(out.read_text(encoding="utf-8"))
    if err.exists():
        print(err.read_text(encoding="utf-8"))
