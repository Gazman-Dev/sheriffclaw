# File: services/sheriff_ctl/ctl.py

from __future__ import annotations

import argparse
import os
import sys
import warnings

if os.getenv("SHERIFF_DEBUG", "0") not in {"1", "true", "yes"}:
    try:
        from urllib3.exceptions import NotOpenSSLWarning

        warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
    except Exception:
        pass

from services.sheriff_ctl.chat import cmd_call, cmd_chat, cmd_entry, cmd_skill
from services.sheriff_ctl.doctor import add_doctor_parser
from services.sheriff_ctl.onboard import cmd_configure_llm, cmd_logout_llm, cmd_onboard
from services.sheriff_ctl.sandbox import cmd_sandbox
from services.sheriff_ctl.service_runner import ALL, cmd_logs, cmd_start, cmd_status, cmd_stop
from services.sheriff_ctl.system import cmd_debug, cmd_factory_reset, cmd_update


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sheriff-ctl")
    sub = p.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("start")
    st.add_argument("--master-password", default=None, help="Unlock vault after start (or set SHERIFF_MASTER_PASSWORD)")
    st.set_defaults(func=cmd_start)
    sub.add_parser("stop").set_defaults(func=cmd_stop)
    sub.add_parser("status").set_defaults(func=cmd_status)
    lg = sub.add_parser("logs")
    lg.add_argument("service", choices=ALL)
    lg.set_defaults(func=cmd_logs)

    for onboard_name in ("onboard", "onboarding"):
        ob = sub.add_parser(onboard_name)
        ob.add_argument("--master-password", default=None)
        ob.add_argument("--llm-provider", default=None)
        ob.add_argument("--llm-api-key", default=None)
        ob.add_argument("--llm-bot-token", default=None)
        ob.add_argument("--gate-bot-token", default=None)
        ob.add_argument("--keep-unchanged", action="store_true", help="When re-onboarding, Enter keeps existing values")

        tg_group = ob.add_mutually_exclusive_group()
        tg_group.add_argument("--allow-telegram", action="store_true", help="Non-interactive: Allow telegram unlock")
        tg_group.add_argument("--deny-telegram", action="store_true", help="Non-interactive: Deny telegram unlock")

        ob.set_defaults(func=cmd_onboard)

    fr = sub.add_parser("factory-reset")
    fr.add_argument("--yes", action="store_true", help="Skip confirmation prompts")
    fr.set_defaults(func=cmd_factory_reset)

    dbg = sub.add_parser("debug")
    dbg.add_argument("debug_args", nargs=argparse.REMAINDER)
    dbg.set_defaults(func=cmd_debug)

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

    upd = sub.add_parser("update")
    upd.add_argument("--master-password", default=None)
    upd.add_argument("--no-pull", action="store_true", help="Skip git pull and only reinstall current source")
    upd.add_argument("--force", action="store_true", help="Force reinstall even if component versions did not increase")
    upd.set_defaults(func=cmd_update)

    sbox = sub.add_parser("sandbox")
    sbox.add_argument("--user", default=None, help="Run ai-worker as this OS user (empty to clear)")
    sbox.add_argument("--allow-net", action="store_true", default=None)
    sbox.add_argument("--deny-net", action="store_false", dest="allow_net")
    sbox.set_defaults(func=cmd_sandbox)

    cfg = sub.add_parser("configure-llm")
    cfg.add_argument("--provider", default="openai-codex")
    cfg.add_argument("--api-key", default=None)
    cfg.add_argument("--master-password", default=None, help="Required if vault is locked")
    cfg.set_defaults(func=cmd_configure_llm)

    logout = sub.add_parser("logout-llm")
    logout.add_argument("--master-password", default=None, help="Required if vault is locked")
    logout.set_defaults(func=cmd_logout_llm)

    add_doctor_parser(sub)

    chat = sub.add_parser("chat")
    chat.add_argument("--principal", default="local-cli")
    chat.add_argument("--model-ref", default=None, help="Model route, e.g. test/default")
    chat.set_defaults(func=cmd_chat)
    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


def main_sheriff(argv: list[str] | None = None) -> None:
    argv = list(argv or sys.argv[1:])
    if argv and argv[0] == "--debug":
        os.environ["SHERIFF_DEBUG"] = "1"
        argv = argv[1:]

    # Route full CLI surface through `sheriff` so users don't need sheriff-ctl.
    ctl_commands = {
        "start",
        "stop",
        "status",
        "logs",
        "onboard",
        "onboarding",
        "factory-reset",
        "debug",
        "skill",
        "call",
        "update",
        "sandbox",
        "configure-llm",
        "logout-llm",
        "doctor",
        "chat",
    }
    if argv and argv[0] in ctl_commands:
        main(argv)
        return

    p = argparse.ArgumentParser(prog="sheriff")
    p.add_argument("message", nargs="*")
    args = p.parse_args(argv)
    if len(args.message) == 1 and args.message[0].lower() == "status":
        cmd_status(argparse.Namespace())
        return
    cmd_entry(args)
