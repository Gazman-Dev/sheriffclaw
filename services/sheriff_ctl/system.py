# File: services/sheriff_ctl/system.py

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path

from shared.paths import gw_root
from shared.proc_rpc import ProcClient
from services.sheriff_ctl.service_runner import ALL, cmd_start, cmd_stop, _stop_service
from services.sheriff_ctl.utils import (
    _clear_telegram_unlock_channel,
    _notify_sheriff_channel,
    _verify_master_password_async,
)


def _wipe_all_state() -> None:
    base = gw_root().parent
    for name in ("gw", "llm"):
        target = base / name
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)


def cmd_factory_reset(args):
    if not args.yes:
        print("This will delete ALL Sheriff/Agent data: vault, chats, skills state, logs, and runtime data.")
        ans1 = input("Proceed with factory reset? [y/N]: ").strip().lower()
        if ans1 not in ("y", "yes"):
            print("Factory reset cancelled.")
            return
        ans2 = input("Are you sure? This cannot be undone. [y/N]: ").strip().lower()
        if ans2 not in ("y", "yes"):
            print("Factory reset cancelled.")
            return

    print("Factory reset in progress (aggressive wipe)...")
    for svc in reversed(ALL):
        _stop_service(svc)
    _wipe_all_state()
    _clear_telegram_unlock_channel()
    print("Factory reset complete. All Sheriff/Agent state removed.")


def cmd_update(args):
    mp = getattr(args, "master_password", None)
    _notify_sheriff_channel("🔄 Sheriff update started.")

    async def _run_update() -> tuple[bool, str, bool]:
        gw = ProcClient("sheriff-gateway")
        updater = ProcClient("sheriff-updater")

        _, plan_res = await updater.request("updater.plan", {"force": bool(getattr(args, "force", False))})
        plan = plan_res.get("result", {})
        if plan.get("needs_master_password"):
            nonlocal mp
            if not mp:
                if not sys.stdin.isatty():
                    return False, "Master password required for secrets update. Pass --master-password in non-interactive mode.", True
                mp = getpass.getpass("Master password for update (secrets version increased): ")
            if not await _verify_master_password_async(mp):
                return False, "Invalid master password. Update cancelled."

        await gw.request("gateway.queue.control", {"pause": True, "reason": "update"})
        try:
            # wait for in-flight agent work to finish
            for _ in range(120):
                _, st = await gw.request("gateway.queue.status", {})
                r = st.get("result", {})
                if int(r.get("processing", 0)) == 0:
                    break
                import asyncio as _a
                await _a.sleep(0.5)

            _, res = await updater.request(
                "updater.run",
                {
                    "master_password": mp,
                    "auto_pull": not getattr(args, "no_pull", False),
                    "force": bool(getattr(args, "force", False)),
                },
            )
            result = res.get("result", {})
            secrets_changed = bool((((result.get("plan") or {}).get("changes") or {}).get("secrets") or {}).get("increased"))
            if result.get("ok") and result.get("mode") == "skipped":
                return True, "No component version increased; update skipped. Use --force to reinstall anyway.", False
            return bool(result.get("ok")), "", secrets_changed
        finally:
            await gw.request("gateway.queue.control", {"pause": False})

    ok, note, secrets_changed = asyncio.run(_run_update())
    if note:
        print(note)
    if ok:
        if "skipped" in note.lower():
            _notify_sheriff_channel("ℹ️ Sheriff update skipped (versions not increased).")
            return
        if secrets_changed:
            print("Restarting managed services after secrets update...")
            cmd_stop(argparse.Namespace())
            start_mp = mp if (mp and isinstance(mp, str) and mp.strip()) else None
            cmd_start(argparse.Namespace(master_password=start_mp))
            if not start_mp:
                print("Note: services restarted without master password; vault may remain locked until /unlock.")
                _notify_sheriff_channel("🔒 Sheriff updated (secrets changed) and restarted; send /unlock <master_password>.")
            else:
                _notify_sheriff_channel("✅ Sheriff update completed (secrets changed) and services restarted unlocked.")
        else:
            print("Secrets version unchanged; preserving running secrets service (no lock reset).")
            _notify_sheriff_channel("✅ Sheriff update completed. Secrets unchanged; unlock state preserved.")
        print("Update completed.")
    else:
        _notify_sheriff_channel("❌ Sheriff update failed. Check logs.")
        print("Update failed.")


def cmd_debug(args):
    os.environ["SHERIFF_DEBUG"] = "1"
    d_args = getattr(args, "debug_args", [])
    if not d_args:
        print("Usage: sheriff debug [folder] [subfolder] [args...]")
        return

    # Dynamic routing for debug paths
    # e.g. sheriff debug channel telegram user-agent "msg"
    root = Path(__file__).resolve().parents[2]
    if len(d_args) >= 2:
        script_path = root / "debug" / d_args[0] / d_args[1] / f"{d_args[1]}_debug.py"
        if script_path.exists():
            env = os.environ.copy()
            env["SHERIFF_DEBUG"] = "1"
            subprocess.run([sys.executable, str(script_path)] + d_args[2:], env=env)
            return

    print(f"Debug script not found for path: debug/{d_args[0]}/{d_args[1]}/{d_args[1]}_debug.py")
