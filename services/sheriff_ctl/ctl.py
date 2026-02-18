from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from shared.paths import gw_root, llm_root
from shared.proc_rpc import ProcClient

GW_ORDER = [
    "sheriff-secrets",
    "sheriff-policy",
    "sheriff-requests",
    "sheriff-web",
    "sheriff-tools",
    "sheriff-gateway",
    "sheriff-tg-gate",
]
LLM_ORDER = ["ai-worker", "ai-tg-llm"]
ALL = [*GW_ORDER, *LLM_ORDER]


def _island_root(service: str) -> Path:
    return gw_root() if service.startswith("sheriff-") else llm_root()


def _pid_path(service: str) -> Path:
    return _island_root(service) / "run" / f"{service}.pid"


def _log_paths(service: str) -> tuple[Path, Path]:
    root = _island_root(service) / "logs"
    return root / f"{service}.out", root / f"{service}.err"


def _start_service(service: str) -> None:
    out_path, err_path = _log_paths(service)
    out = out_path.open("a", encoding="utf-8")
    err = err_path.open("a", encoding="utf-8")
    proc = subprocess.Popen([service], stdout=out, stderr=err)  # noqa: S603
    _pid_path(service).write_text(str(proc.pid), encoding="utf-8")


def _read_pid(service: str) -> int | None:
    p = _pid_path(service)
    if not p.exists():
        return None
    try:
        return int(p.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _stop_service(service: str) -> None:
    pid = _read_pid(service)
    if pid is None:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _pid_path(service).unlink(missing_ok=True)
        return
    deadline = time.time() + 3
    while time.time() < deadline and _alive(pid):
        time.sleep(0.1)
    if _alive(pid):
        os.kill(pid, signal.SIGKILL)
    _pid_path(service).unlink(missing_ok=True)


def cmd_start(args):
    for svc in ALL:
        _start_service(svc)


def cmd_stop(args):
    for svc in reversed(ALL):
        _stop_service(svc)


def cmd_status(args):
    for svc in ALL:
        pid = _read_pid(svc)
        print(f"{svc}: {pid if pid and _alive(pid) else 'stopped'}")


def cmd_logs(args):
    out, err = _log_paths(args.service)
    if out.exists():
        print(out.read_text(encoding="utf-8"))
    if err.exists():
        print(err.read_text(encoding="utf-8"))


def cmd_onboard(args):
    print("=== SheriffClaw Onboarding ===")

    mp = args.master_password
    if mp is None:
        while not mp:
            mp = getpass.getpass("Set Master Password: ")

    llm_prov = args.llm_provider
    if llm_prov is None:
        llm_prov = input("LLM Provider (stub/openai/anthropic) [stub]: ").strip() or "stub"

    llm_key = args.llm_api_key
    if llm_key is None:
        llm_key = getpass.getpass(f"API Key for {llm_prov} (enter to skip): ").strip()

    llm_bot = args.llm_bot_token
    if llm_bot is None:
        llm_bot = input("Telegram Bot Token for LLM (enter to skip): ").strip()

    gate_bot = args.gate_bot_token
    if gate_bot is None:
        gate_bot = input("Telegram Bot Token for Gate (enter to skip): ").strip()

    allow_tg = False
    if args.allow_telegram:
        allow_tg = True
    elif args.deny_telegram:
        allow_tg = False
    else:
        ans = input("Allow sending master password via Telegram to unlock? [y/N]: ").strip().lower()
        allow_tg = ans in ("y", "yes")

    print(f"\nConfiguration:\nProvider: {llm_prov}\nTelegram Unlock: {allow_tg}\nSaving...")

    master_policy = gw_root() / "state" / "master_policy.json"
    master_policy.parent.mkdir(parents=True, exist_ok=True)
    master_policy.write_text(json.dumps({"allow_telegram_master_password": allow_tg}), encoding="utf-8")

    async def _run():
        cli = ProcClient("sheriff-secrets")
        # Give services a moment to be ready if we just started them
        for _ in range(5):
            try:
                await cli.request("health", {})
                break
            except Exception:
                await asyncio.sleep(1)

        await cli.request(
            "secrets.initialize",
            {
                "master_password": mp,
                "llm_provider": llm_prov,
                "llm_api_key": llm_key,
                "llm_bot_token": llm_bot,
                "gate_bot_token": gate_bot,
                "allow_telegram_master_password": allow_tg,
            },
        )
        await cli.request("secrets.unlock", {"master_password": mp})

    asyncio.run(_run())
    print("Onboarding complete. Secrets initialized and unlocked.")


def cmd_skill(args):
    async def _run():
        cli = ProcClient("ai-worker")
        _, resp = await cli.request("skill.main", {"argv": [args.name, *args.argv], "stdin": args.stdin})
        print(resp["result"]["stdout"])

    asyncio.run(_run())


def cmd_call(args):
    async def _run():
        cli = ProcClient(args.service)
        stream, final = await cli.request(args.op, json.loads(args.json), stream_events=True)
        async for frame in stream:
            print(json.dumps(frame, ensure_ascii=False))
        print(json.dumps(await final, ensure_ascii=False))

    asyncio.run(_run())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sheriff-ctl")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("start").set_defaults(func=cmd_start)
    sub.add_parser("stop").set_defaults(func=cmd_stop)
    sub.add_parser("status").set_defaults(func=cmd_status)
    lg = sub.add_parser("logs")
    lg.add_argument("service", choices=ALL)
    lg.set_defaults(func=cmd_logs)

    ob = sub.add_parser("onboard")
    ob.add_argument("--master-password", default=None)
    ob.add_argument("--llm-provider", default=None)
    ob.add_argument("--llm-api-key", default=None)
    ob.add_argument("--llm-bot-token", default=None)
    ob.add_argument("--gate-bot-token", default=None)

    tg_group = ob.add_mutually_exclusive_group()
    tg_group.add_argument("--allow-telegram", action="store_true", help="Non-interactive: Allow telegram unlock")
    tg_group.add_argument("--deny-telegram", action="store_true", help="Non-interactive: Deny telegram unlock")

    ob.set_defaults(func=cmd_onboard)

    sp = sub.add_parser("skill")
    sp.add_argument("name")
    sp.add_argument("argv", nargs="*")
    sp.add_argument("--stdin", default="")
    sp.set_defaults(func=cmd_skill)

    cl = sub.add_parser("call")
    cl.add_argument("service")
    cl.add_argument("op")
    cl.add_argument("--json", default="{}")
    cl.set_defaults(func=cmd_call)
    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)