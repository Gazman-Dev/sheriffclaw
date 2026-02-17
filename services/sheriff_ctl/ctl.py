from __future__ import annotations

import argparse
import asyncio
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
    master_policy = gw_root() / "state" / "master_policy.json"
    master_policy.write_text(json.dumps({"allow_telegram_master_password": bool(args.allow_telegram_master_password)}), encoding="utf-8")

    async def _run():
        cli = ProcClient("sheriff-secrets")
        await cli.request(
            "secrets.initialize",
            {
                "master_password": args.master_password,
                "llm_provider": args.llm_provider,
                "llm_api_key": args.llm_api_key,
                "llm_bot_token": args.llm_bot_token,
                "gate_bot_token": args.gate_bot_token,
                "allow_telegram_master_password": args.allow_telegram_master_password,
            },
        )
        await cli.request("secrets.unlock", {"master_password": args.master_password})

    asyncio.run(_run())
    print("onboarded")


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
    ob.add_argument("--master-password", default="devpass")
    ob.add_argument("--llm-provider", default="stub")
    ob.add_argument("--llm-api-key", default="")
    ob.add_argument("--llm-bot-token", default="")
    ob.add_argument("--gate-bot-token", default="")
    ob.add_argument("--allow-telegram-master-password", action="store_true")
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