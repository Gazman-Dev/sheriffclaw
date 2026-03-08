# File: services/sheriff_ctl/service_runner.py

from __future__ import annotations

import asyncio
import os
import platform
import shutil

try:
    import pwd
except ImportError:  # pragma: no cover - Windows
    pwd = None

from services.sheriff_ctl.sandbox import (
    _darwin_ai_worker_launcher_path,
    _ai_worker_sandbox_profile,
    _ai_worker_user,
    _linux_sandbox_profile,
    _strict_sandbox_required,
)
from services.sheriff_ctl.utils import (
    _log_paths,
    _notify_sheriff_channel,
    _pid_path,
    _service_exec_command,
)
from shared.proc_rpc import ProcClient
from shared.service_registry import rpc_endpoint
from shared.service_manager import ServiceManager

GW_ORDER =[
    "sheriff-secrets",
    "sheriff-policy",
    "sheriff-web",
    "sheriff-tools",
    "sheriff-gateway",
    "sheriff-chat-proxy",
    "sheriff-tg-gate",
    "sheriff-requests",
    "sheriff-cli-gate",
    "sheriff-updater",
]
LLM_ORDER =["ai-worker", "ai-tg-llm", "telegram-listener"]
ALL =[*GW_ORDER, *LLM_ORDER]

MANAGED_SERVICES = ALL


def _posix_user_exists(user: str) -> bool:
    if not user:
        return False
    if platform.system() not in {"Darwin", "Linux"}:
        return True
    if pwd is None:
        return False
    try:
        pwd.getpwnam(user)
        return True
    except KeyError:
        return False

def _service_command(service: str) -> list[str]:
    base = _service_exec_command(service)
    if service == "ai-worker":
        sandboxed = None
        if platform.system() == "Darwin":
            user = _ai_worker_user()
            if user:
                if not _posix_user_exists(user):
                    raise RuntimeError(f"configured ai-worker user does not exist: {user}")
                launcher = _darwin_ai_worker_launcher_path()
                if not launcher.exists():
                    raise RuntimeError(
                        f"missing macOS ai-worker launcher: {launcher} (rerun installer)")
                sandboxed = [str(launcher)]
            else:
                sb = shutil.which("sandbox-exec")
                if sb:
                    profile = _ai_worker_sandbox_profile()
                    sandboxed = [sb, "-f", str(profile), *base]
        elif platform.system() == "Linux":
            bwrap = shutil.which("bwrap")
            if bwrap:
                profile = _linux_sandbox_profile()
                args =[ln.strip() for ln in profile.read_text(encoding="utf-8").splitlines() if ln.strip()]
                sandboxed = [bwrap, *args, *base]

        if sandboxed is None:
            if _strict_sandbox_required():
                raise RuntimeError(
                    "strict sandbox enabled: ai-worker sandbox runtime missing (need sandbox-exec or bwrap)")
            sandboxed = base

        user = _ai_worker_user()
        if user and platform.system() in {"Darwin", "Linux"}:
            sudo = shutil.which("sudo")
            if platform.system() != "Darwin" and not _posix_user_exists(user):
                raise RuntimeError(f"configured ai-worker user does not exist: {user}")
            if not sudo:
                raise RuntimeError("sudo is required to run ai-worker under a dedicated OS user")
            sandboxed =[sudo, "-n", "-u", user, *sandboxed]

        return sandboxed
    return base


def _service_env(service: str) -> dict[str, str]:
    env = os.environ.copy()
    endpoint = rpc_endpoint(service)
    if endpoint is not None:
        env["SHERIFF_RPC_HOST"] = endpoint[0]
        env["SHERIFF_RPC_PORT"] = str(endpoint[1])
    return env


SERVICE_MANAGER = ServiceManager(_service_command, _pid_path, _log_paths, _service_env)


def _start_service(service: str) -> None:
    SERVICE_MANAGER.start(service)


def _read_pid(service: str) -> int | None:
    return SERVICE_MANAGER.read_pid(service)


def _alive(pid: int) -> bool:
    return SERVICE_MANAGER.alive(pid)


def _stop_service(service: str) -> None:
    SERVICE_MANAGER.stop(service)


async def _wait_service_health(service: str, timeout_sec: float = 10.0) -> None:
    endpoint = rpc_endpoint(service)
    if endpoint is None:
        await asyncio.sleep(0.2)
        return
    cli = ProcClient(service, spawn_fallback=False)
    deadline = asyncio.get_running_loop().time() + timeout_sec
    try:
        while True:
            try:
                await cli.request("health", {})
                return
            except Exception:
                if asyncio.get_running_loop().time() >= deadline:
                    raise
                await asyncio.sleep(0.2)
    finally:
        await cli.close()


def cmd_start(args):
    mp = getattr(args, "master_password", None) or os.getenv("SHERIFF_MASTER_PASSWORD", "")

    to_restart = list(MANAGED_SERVICES)

    # Restart managed services we selected to avoid stale old binaries.
    SERVICE_MANAGER.stop_many(list(reversed(to_restart)))

    async def _start_all() -> None:
        for service in to_restart:
            SERVICE_MANAGER.start(service)
            await _wait_service_health(service)

    asyncio.run(_start_all())

    async def _check_and_unlock():
        secrets = ProcClient("sheriff-secrets", spawn_fallback=False)
        try:
            for _ in range(15):
                try:
                    await secrets.request("health", {})
                    break
                except Exception:
                    await asyncio.sleep(0.3)

            # Check if already unlocked (via secrets_session.json)
            _, res_unl = await secrets.request("secrets.is_unlocked", {})
            if res_unl.get("result", {}).get("unlocked"):
                return True, True  # (is_unlocked, was_auto_unlocked)

            if mp:
                _, res = await secrets.request("secrets.unlock", {"master_password": mp})
                return bool(res.get("result", {}).get("ok")), False
            return False, False
        finally:
            await secrets.close()

    ok, auto = asyncio.run(_check_and_unlock())
    if ok:
        if auto and not mp:
            print("Vault auto-unlocked from session.")
        else:
            print("Vault unlocked on start.")
            _notify_sheriff_channel("✅ Sheriff services restarted and vault unlocked.")
    else:
        print("Warning: vault is locked. Master password required.")
        _notify_sheriff_channel("🔒 Sheriff restarted but vault is locked. Send: /unlock <master_password>")


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
