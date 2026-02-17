from __future__ import annotations

import argparse
import os
import signal
import subprocess
from pathlib import Path

from python_openclaw.cli.onboard import run_onboarding
from shared.paths import gw_root, llm_root
from shared.proc_rpc import ProcClient

GW_ORDER = [
    "sheriff-secrets",
    "sheriff-policy",
    "sheriff-web",
    "sheriff-tools",
    "sheriff-gateway",
    "sheriff-tg-gate",
]
LLM_ORDER = ["ai-worker", "ai-tg-llm"]


def _pid_dir(service: str) -> Path:
    root = gw_root() if service.startswith("sheriff-") else llm_root()
    p = root / "run"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _pid_path(service: str) -> Path:
    return _pid_dir(service) / f"{service}.pid"


def _start_service(service: str) -> None:
    proc = subprocess.Popen([service], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
    _pid_path(service).write_text(str(proc.pid), encoding="utf-8")


def _stop_service(service: str) -> None:
    p = _pid_path(service)
    if not p.exists():
        return
    pid = int(p.read_text(encoding="utf-8"))
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    p.unlink(missing_ok=True)


def cmd_start(args):
    for svc in [*GW_ORDER, *LLM_ORDER]:
        _start_service(svc)


def cmd_stop(args):
    for svc in reversed([*GW_ORDER, *LLM_ORDER]):
        _stop_service(svc)


def cmd_status(args):
    for svc in [*GW_ORDER, *LLM_ORDER]:
        p = _pid_path(svc)
        state = p.read_text(encoding="utf-8").strip() if p.exists() else "stopped"
        print(f"{svc}: {state}")


def cmd_onboard(args):
    run_onboarding()


def cmd_skill(args):
    import asyncio

    async def _run():
        cli = ProcClient("ai-worker")
        _, resp = await cli.request("skill.main", {"argv": [args.name, *args.argv], "stdin": args.stdin})
        print(resp["result"]["stdout"])

    asyncio.run(_run())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sheriff-ctl")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("start").set_defaults(func=cmd_start)
    sub.add_parser("stop").set_defaults(func=cmd_stop)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("onboard").set_defaults(func=cmd_onboard)
    sp = sub.add_parser("skill")
    sp.add_argument("name")
    sp.add_argument("argv", nargs="*")
    sp.add_argument("--stdin", default="")
    sp.set_defaults(func=cmd_skill)
    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
