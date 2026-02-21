from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import warnings
from pathlib import Path

from shared.paths import gw_root, llm_root
from shared.proc_rpc import ProcClient

if os.getenv("SHERIFF_DEBUG", "0") not in {"1", "true", "yes"}:
    try:
        from urllib3.exceptions import NotOpenSSLWarning

        warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
    except Exception:
        pass

GW_ORDER = [
    "sheriff-secrets",
    "sheriff-policy",
    "sheriff-requests",
    "sheriff-web",
    "sheriff-tools",
    "sheriff-gateway",
    "sheriff-tg-gate",
    "sheriff-cli-gate",
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


def _resolve_service_binary(service: str) -> str:
    venv_bin = Path(sys.executable).parent / service
    return str(venv_bin) if venv_bin.exists() else service


def _start_service(service: str) -> None:
    out_path, err_path = _log_paths(service)
    out = out_path.open("a", encoding="utf-8")
    err = err_path.open("a", encoding="utf-8")
    proc = subprocess.Popen([_resolve_service_binary(service)], stdout=out, stderr=err)  # noqa: S603
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


def _wipe_all_state() -> None:
    base = gw_root().parent
    for name in ("gw", "llm"):
        target = base / name
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)


def cmd_reinstall(args):
    if not args.yes:
        print("This will delete ALL Sheriff/Agent data: vault, chats, skills state, logs, and runtime data.")
        ans1 = input("Proceed with reinstall? [y/N]: ").strip().lower()
        if ans1 not in ("y", "yes"):
            print("Reinstall cancelled.")
            return
        ans2 = input("Are you sure? This cannot be undone. [y/N]: ").strip().lower()
        if ans2 not in ("y", "yes"):
            print("Reinstall cancelled.")
            return

    print("Reinstalling SheriffClaw state (aggressive wipe)...")
    for svc in reversed(ALL):
        _stop_service(svc)
    _wipe_all_state()
    print("Reinstall complete. All Sheriff/Agent state removed.")


def cmd_onboard(args):
    print("=== SheriffClaw Onboarding ===")

    mp = args.master_password
    if mp is None:
        while True:
            a = getpass.getpass("Set Master Password: ")
            b = getpass.getpass("Confirm Master Password: ")
            if a and a == b:
                mp = a
                break
            print("Passwords do not match. Please try again.")

    llm_prov = args.llm_provider
    llm_key = args.llm_api_key
    llm_auth = None

    if llm_prov is None:
        while True:
            print("\nChoose your LLM:")
            print("1) OpenAI Codex (API key)")
            print("2) OpenAI Codex (ChatGPT subscription login)")
            print("3) Local stub (testing only)")
            choice = input("Select [1/2/3] (default 1): ").strip() or "1"

            if choice == "3":
                llm_prov = "stub"
                llm_key = ""
                break

            if choice == "1":
                llm_prov = "openai-codex"
                llm_key = getpass.getpass("OpenAI API Key: ").strip()
                break

            if choice == "2":
                print("Starting ChatGPT subscription device login...")
                from shared.llm.device_auth import run_browser_oauth_login
                try:
                    tokens = run_browser_oauth_login(timeout_seconds=900)
                except RuntimeError as e:
                    print(f"Login cancelled/failed: {e}")
                    continue
                llm_prov = "openai-codex-chatgpt"
                llm_key = ""
                llm_auth = {
                    "type": "chatgpt_subscription_device_code",
                    "access_token": tokens.access_token,
                    "refresh_token": tokens.refresh_token,
                    "id_token": tokens.id_token,
                    "obtained_at": tokens.obtained_at,
                    "expires_at": tokens.expires_at,
                }
                break

    if llm_key is None:
        if llm_prov == "openai-codex":
            llm_key = getpass.getpass("OpenAI API Key: ").strip()
        else:
            llm_key = ""

    channel = "telegram"
    print("\nChannel setup:")
    print("- Telegram is currently the supported channel")

    llm_bot = args.llm_bot_token
    if llm_bot is None:
        llm_bot = input("Telegram AI bot token (BotFather): ").strip()

    gate_bot = args.gate_bot_token
    if gate_bot is None:
        gate_bot = input("Telegram Sheriff bot token (BotFather): ").strip()

    allow_tg = False
    if args.allow_telegram:
        allow_tg = True
    elif args.deny_telegram:
        allow_tg = False
    else:
        ans = input("Allow sending master password via Telegram to unlock? [y/N]: ").strip().lower()
        allow_tg = ans in ("y", "yes")

    print(f"\nConfiguration:\nProvider: {llm_prov}\nChannel: telegram\nTelegram Unlock: {allow_tg}\nSaving...")

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
        if llm_auth:
            await cli.request("secrets.set_llm_auth", {"auth": llm_auth})

        # Activation flow: AI bot first, then Sheriff bot
        interactive_codes = sys.stdin.isatty()

        if llm_bot and interactive_codes:
            print("\nAI bot activation:")
            print("1) Send any message to the AI bot in Telegram.")
            print("2) Bot should return a 5-letter activation code.")
            while True:
                code = input("Enter AI bot activation code: ").strip().lower()
                _, claimed = await cli.request("secrets.activation.claim", {"bot_role": "llm", "code": code})
                if claimed.get("result", {}).get("ok"):
                    print("AI bot activated.")
                    break
                print("Invalid code, try again.")

        if gate_bot and interactive_codes:
            print("\nSheriff bot activation:")
            print("1) Send any message to the Sheriff bot in Telegram.")
            print("2) Bot should return a 5-letter activation code.")
            while True:
                code = input("Enter Sheriff bot activation code: ").strip().lower()
                _, claimed = await cli.request("secrets.activation.claim", {"bot_role": "sheriff", "code": code})
                if claimed.get("result", {}).get("ok"):
                    print("Sheriff bot activated.")
                    break
                print("Invalid code, try again.")

        if (llm_bot or gate_bot) and not interactive_codes:
            print("Skipping activation code prompts in non-interactive mode.")

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


def cmd_logout_llm(args):
    async def _run():
        cli = ProcClient("sheriff-secrets")
        _, unlocked = await cli.request("secrets.is_unlocked", {})
        if not unlocked.get("result", {}).get("unlocked"):
            if not args.master_password:
                raise RuntimeError("vault is locked; pass --master-password")
            _, res = await cli.request("secrets.unlock", {"master_password": args.master_password})
            if not res.get("result", {}).get("ok"):
                raise RuntimeError("failed to unlock vault with provided master password")
        await cli.request("secrets.set_llm_api_key", {"api_key": ""})
        await cli.request("secrets.clear_llm_auth", {})

    asyncio.run(_run())
    print("LLM auth cleared from vault.")


def cmd_configure_llm(args):
    provider = args.provider or "openai-codex"
    api_key = args.api_key
    if api_key is None:
        api_key = getpass.getpass(f"API key for {provider}: ").strip()

    async def _run():
        cli = ProcClient("sheriff-secrets")
        _, unlocked = await cli.request("secrets.is_unlocked", {})
        if not unlocked.get("result", {}).get("unlocked"):
            if not args.master_password:
                raise RuntimeError("vault is locked; pass --master-password to configure llm")
            _, res = await cli.request("secrets.unlock", {"master_password": args.master_password})
            if not res.get("result", {}).get("ok"):
                raise RuntimeError("failed to unlock vault with provided master password")

        await cli.request("secrets.set_llm_provider", {"provider": provider})
        await cli.request("secrets.set_llm_api_key", {"api_key": api_key})

    asyncio.run(_run())
    print(f"LLM provider configured: {provider}")


def cmd_chat(args):
    principal = args.principal
    model_ref = args.model_ref

    async def _send_bot(gateway: ProcClient, text: str):
        stream, final = await gateway.request(
            "gateway.handle_user_message",
            {"channel": "cli", "principal_external_id": principal, "text": text, "model_ref": model_ref},
            stream_events=True,
        )
        bot_printed = False
        async for frame in stream:
            event = frame.get("event")
            payload = frame.get("payload", {})
            if event == "assistant.delta":
                print(f"[AGENT] {payload.get('text', '')}")
                bot_printed = True
            elif event == "assistant.final" and not bot_printed:
                print(f"[AGENT] {payload.get('text', '')}")
                bot_printed = True
            elif event == "tool.result":
                print(f"[TOOL] {json.dumps(payload, ensure_ascii=False)}")
        await final

    async def _send_sheriff(cli_gate: ProcClient, text: str):
        _, res = await cli_gate.request("cli.handle_message", {"text": text})
        msg = res.get("result", {}).get("message", "")
        kind = res.get("result", {}).get("kind", "sheriff").upper()
        print(f"[{kind}] {msg}")

    async def _run():
        gateway = ProcClient("sheriff-gateway")
        cli_gate = ProcClient("sheriff-cli-gate")
        print("SheriffClaw terminal chat")
        print("- Enter sends a single-line message")
        print("- /... routes to Sheriff, anything else routes to Agent")
        print("- Type /quit or /exit to leave")
        while True:
            try:
                line = await asyncio.to_thread(input, "> ")
            except (EOFError, KeyboardInterrupt):
                print("\nbye")
                return
            text = line.rstrip("\n")
            if not text:
                continue
            if text in {"/quit", "/exit"}:
                print("bye")
                return
            if text.startswith("/"):
                await _send_sheriff(cli_gate, text)
            else:
                await _send_bot(gateway, text)

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

    for onboard_name in ("onboard", "onboarding"):
        ob = sub.add_parser(onboard_name)
        ob.add_argument("--master-password", default=None)
        ob.add_argument("--llm-provider", default=None)
        ob.add_argument("--llm-api-key", default=None)
        ob.add_argument("--llm-bot-token", default=None)
        ob.add_argument("--gate-bot-token", default=None)

        tg_group = ob.add_mutually_exclusive_group()
        tg_group.add_argument("--allow-telegram", action="store_true", help="Non-interactive: Allow telegram unlock")
        tg_group.add_argument("--deny-telegram", action="store_true", help="Non-interactive: Deny telegram unlock")

        ob.set_defaults(func=cmd_onboard)

    reinstall = sub.add_parser("reinstall")
    reinstall.add_argument("--yes", action="store_true", help="Skip confirmation prompts")
    reinstall.set_defaults(func=cmd_reinstall)

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

    cfg = sub.add_parser("configure-llm")
    cfg.add_argument("--provider", default="openai-codex")
    cfg.add_argument("--api-key", default=None)
    cfg.add_argument("--master-password", default=None, help="Required if vault is locked")
    cfg.set_defaults(func=cmd_configure_llm)

    logout = sub.add_parser("logout-llm")
    logout.add_argument("--master-password", default=None, help="Required if vault is locked")
    logout.set_defaults(func=cmd_logout_llm)

    chat = sub.add_parser("chat")
    chat.add_argument("--principal", default="local-cli")
    chat.add_argument("--model-ref", default=None, help="Model route, e.g. test/default")
    chat.set_defaults(func=cmd_chat)
    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)