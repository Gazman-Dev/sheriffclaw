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
import select
import termios
import tty

# requests is imported lazily in onboarding activation flow to avoid noisy startup warnings.

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
LLM_ORDER = ["ai-worker", "ai-tg-llm", "telegram-webhook"]
ALL = [*GW_ORDER, *LLM_ORDER]


def _debug_mode_path() -> Path:
    return gw_root() / "state" / "debug_mode.json"


def _debug_messages_path() -> Path:
    return gw_root() / "state" / "debug.agent.jsonl"


def _read_debug_mode() -> bool:
    p = _debug_mode_path()
    if not p.exists():
        return False
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        return bool(obj.get("enabled", False))
    except Exception:
        return False


def _write_debug_mode(enabled: bool) -> None:
    p = _debug_mode_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"enabled": enabled}), encoding="utf-8")


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
    pid = _read_pid(service)
    if pid and _alive(pid):
        return
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
    already = [svc for svc in ALL if (_read_pid(svc) and _alive(_read_pid(svc)))]
    if already and sys.stdin.isatty():
        ans = input(f"Services already running ({', '.join(already)}). Stop and restart? [y/N]: ").strip().lower()
        if ans in ("y", "yes"):
            for svc in reversed(already):
                _stop_service(svc)
        else:
            print("Start cancelled.")
            return

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
    print("Factory reset complete. All Sheriff/Agent state removed.")


def _verify_master_password(mp: str) -> bool:
    async def _run() -> bool:
        cli = ProcClient("sheriff-secrets")
        _, res = await cli.request("secrets.verify_master_password", {"master_password": mp})
        return bool(res.get("result", {}).get("ok"))

    return asyncio.run(_run())


def cmd_update(args):
    repo_root = Path(__file__).resolve().parents[2]
    installer = repo_root / "install.sh"
    if not installer.exists():
        print("Update script not found.")
        return
    subprocess.run(["bash", str(installer)], check=False)  # noqa: S603


def cmd_onboard(args):
    print("=== SheriffClaw Onboarding ===")

    mp = args.master_password
    if mp is None:
        if bool(getattr(args, "keep_unchanged", False)) and _is_onboarded():
            mp = getpass.getpass("Current Master Password (keep unchanged mode): ")
        else:
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
    keep_unchanged = bool(getattr(args, "keep_unchanged", False))
    existing: dict[str, str] = {}

    if keep_unchanged and _is_onboarded():
        async def _load_existing() -> dict[str, str]:
            cli = ProcClient("sheriff-secrets")
            _, ok = await cli.request("secrets.unlock", {"master_password": mp})
            if not ok.get("result", {}).get("ok"):
                raise RuntimeError("failed to unlock with provided master password")
            _, p = await cli.request("secrets.get_llm_provider", {})
            _, k = await cli.request("secrets.get_llm_api_key", {})
            _, la = await cli.request("secrets.get_llm_auth", {})
            _, lb = await cli.request("secrets.get_llm_bot_token", {})
            _, gb = await cli.request("secrets.get_gate_bot_token", {})
            return {
                "llm_provider": p.get("result", {}).get("provider") or "",
                "llm_api_key": k.get("result", {}).get("api_key") or "",
                "llm_auth": la.get("result", {}).get("auth") or {},
                "llm_bot_token": lb.get("result", {}).get("token") or "",
                "gate_bot_token": gb.get("result", {}).get("token") or "",
            }

        try:
            existing = asyncio.run(_load_existing())
            policy_path = gw_root() / "state" / "master_policy.json"
            if policy_path.exists():
                policy = json.loads(policy_path.read_text(encoding="utf-8"))
                existing["allow_telegram_master_password"] = bool(policy.get("allow_telegram_master_password", False))
        except Exception as e:
            raise RuntimeError(f"keep-unchanged requested but could not load existing config: {e}")

    if llm_prov is None:
        while True:
            print("\nChoose your LLM:")
            print("1) OpenAI Codex (API key)")
            print("2) OpenAI Codex (ChatGPT subscription login)")
            print("3) Local stub (testing only)")
            default_choice = "1"
            if keep_unchanged and existing.get("llm_provider"):
                cur = existing.get("llm_provider")
                if cur == "openai-codex-chatgpt":
                    default_choice = "2"
                elif cur == "stub":
                    default_choice = "3"
            if keep_unchanged and existing.get("llm_provider"):
                choice = input("Select [1/2/3] or K to keep current provider: ").strip().lower()
                if not choice or choice == "k":
                    llm_prov = existing.get("llm_provider")
                    llm_key = existing.get("llm_api_key", "")
                    if llm_prov == "openai-codex-chatgpt":
                        llm_auth = existing.get("llm_auth") or None
                    break
            else:
                choice = input(f"Select [1/2/3] (default {default_choice}): ").strip() or default_choice

            if choice == "3":
                llm_prov = "stub"
                llm_key = ""
                break

            if choice == "1":
                llm_prov = "openai-codex"
                if keep_unchanged and existing.get("llm_api_key"):
                    entered = getpass.getpass("OpenAI API Key (Enter=keep unchanged): ").strip()
                    llm_key = entered or existing.get("llm_api_key", "")
                else:
                    llm_key = getpass.getpass("OpenAI API Key: ").strip()
                break

            if choice == "2":
                print("Starting ChatGPT subscription browser login...")
                from shared.llm.device_auth import run_browser_oauth_login
                try:
                    tokens = run_browser_oauth_login(timeout_seconds=900)
                except RuntimeError as e:
                    print(f"Login cancelled/failed: {e}")
                    continue
                llm_prov = "openai-codex-chatgpt"
                llm_key = ""
                llm_auth = {
                    "type": "chatgpt_browser_oauth",
                    "access_token": tokens.access_token,
                    "refresh_token": tokens.refresh_token,
                    "id_token": tokens.id_token,
                    "obtained_at": tokens.obtained_at,
                    "expires_at": tokens.expires_at,
                }
                break

    if llm_key is None:
        if llm_prov == "openai-codex":
            if keep_unchanged and existing.get("llm_api_key"):
                entered = getpass.getpass("OpenAI API Key (Enter=keep unchanged): ").strip()
                llm_key = entered or existing.get("llm_api_key", "")
            else:
                llm_key = getpass.getpass("OpenAI API Key: ").strip()
        else:
            llm_key = ""

    channel = "telegram"
    print("\nChannel setup:")
    print("- Telegram is currently the supported channel")

    llm_bot = args.llm_bot_token
    if llm_bot is None:
        if keep_unchanged and existing.get("llm_bot_token"):
            llm_bot = input("Telegram AI bot token (Enter=keep unchanged): ").strip() or existing.get("llm_bot_token", "")
        else:
            llm_bot = input("Telegram AI bot token (BotFather): ").strip()

    gate_bot = args.gate_bot_token

    allow_tg = False

    async def _telegram_activate_bot(cli: ProcClient, role: str, token: str, timeout_sec: int = 300) -> bool:
        import requests

        print(f"\n{role.upper()} bot activation:")
        print("1) Open Telegram and send any message to the bot.")
        print("2) The bot will reply with an activation code.")
        print("3) Paste that code here.")

        offset = 0
        sent_codes: dict[str, str] = {}
        start = time.time()

        while time.time() - start < timeout_sec:
            # Already activated?
            _, st = await cli.request("secrets.activation.status", {"bot_role": role})
            if st.get("result", {}).get("user_id"):
                return True

            try:
                resp = requests.get(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    params={"timeout": 20, "allowed_updates": '["message"]', "offset": offset},
                    timeout=30,
                )
                data = resp.json()
                updates = data.get("result", []) if isinstance(data, dict) else []
            except Exception:
                updates = []

            for upd in updates:
                update_id = int(upd.get("update_id", 0))
                offset = max(offset, update_id + 1)
                msg = upd.get("message") or {}
                from_user = msg.get("from") or {}
                chat = msg.get("chat") or {}
                user_id = str(from_user.get("id") or "")
                chat_id = chat.get("id")
                if not user_id or chat_id is None:
                    continue

                _, bound = await cli.request("secrets.activation.status", {"bot_role": role})
                bound_uid = bound.get("result", {}).get("user_id")
                if bound_uid and str(bound_uid) == user_id:
                    continue

                code = sent_codes.get(user_id)
                if not code:
                    _, c = await cli.request("secrets.activation.create", {"bot_role": role, "user_id": user_id})
                    code = c.get("result", {}).get("code")
                    if not code:
                        continue
                    sent_codes[user_id] = code

                text = f"Your activation code is: {code}\nReply: activate {code}"
                try:
                    requests.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                        timeout=15,
                    )
                except Exception:
                    pass

            if sent_codes:
                try:
                    code_in = input(f"Enter {role} activation code: ").strip().upper()
                except KeyboardInterrupt:
                    return False
                if not code_in:
                    continue
                _, claim = await cli.request("secrets.activation.claim", {"bot_role": role, "code": code_in})
                if claim.get("result", {}).get("ok"):
                    return True
                print("Invalid code, try again.")
            else:
                print("Waiting for a Telegram DM to the bot...")
                await asyncio.sleep(2)

        return False

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
                "gate_bot_token": "",
                "allow_telegram_master_password": False,
            },
        )
        await cli.request("secrets.unlock", {"master_password": mp})
        if llm_auth:
            await cli.request("secrets.set_llm_auth", {"auth": llm_auth})

        interactive = sys.stdin.isatty()

        if llm_bot:
            await cli.request("secrets.set_llm_bot_token", {"token": llm_bot})
            if interactive:
                ok = await _telegram_activate_bot(cli, "llm", llm_bot)
                if ok:
                    print("AI bot activated.")
                else:
                    print("AI bot activation timed out/cancelled.")

        gate_tok = gate_bot
        if gate_tok is None:
            if keep_unchanged and existing.get("gate_bot_token"):
                gate_tok = input("Telegram Sheriff bot token (Enter=keep unchanged): ").strip() or existing.get("gate_bot_token", "")
            else:
                gate_tok = input("Telegram Sheriff bot token (BotFather): ").strip()

        if gate_tok:
            await cli.request("secrets.set_gate_bot_token", {"token": gate_tok})
            if interactive:
                ok = await _telegram_activate_bot(cli, "sheriff", gate_tok)
                if ok:
                    print("Sheriff bot activated.")
                else:
                    print("Sheriff bot activation timed out/cancelled.")

        if (llm_bot or gate_tok) and not interactive:
            print("Skipping activation wait in non-interactive mode.")

        # Ask unlock policy only after activation phase
        nonlocal allow_tg
        if args.allow_telegram:
            allow_tg = True
        elif args.deny_telegram:
            allow_tg = False
        else:
            if keep_unchanged and "allow_telegram_master_password" in existing:
                cur = "Y" if existing.get("allow_telegram_master_password") else "N"
                ans = input(f"Allow sending master password via Telegram to unlock? [y/N] (Enter=keep {cur}): ").strip().lower()
                if not ans:
                    allow_tg = bool(existing.get("allow_telegram_master_password"))
                else:
                    allow_tg = ans in ("y", "yes")
            else:
                ans = input("Allow sending master password via Telegram to unlock? [y/N]: ").strip().lower()
                allow_tg = ans in ("y", "yes")

        master_policy = gw_root() / "state" / "master_policy.json"
        master_policy.parent.mkdir(parents=True, exist_ok=True)
        master_policy.write_text(json.dumps({"allow_telegram_master_password": allow_tg}), encoding="utf-8")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nOnboarding cancelled.")
        return
    print("Onboarding complete. Secrets initialized and unlocked.")


def cmd_debug(args):
    enabled = str(args.value).lower() == "on"
    _write_debug_mode(enabled)
    print(f"Debug mode {'ON' if enabled else 'OFF'}")


def _wait_extra_or_esc(seconds: int = 10) -> None:
    if not sys.stdin.isatty():
        time.sleep(seconds)
        return

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    end_at = time.time() + seconds
    try:
        tty.setcbreak(fd)
        while time.time() < end_at:
            r, _, _ = select.select([fd], [], [], 0.2)
            if not r:
                continue
            ch = os.read(fd, 1)
            if ch == b"\x1b":
                print("\n(wait cancelled)")
                return
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _is_onboarded() -> bool:
    state = gw_root() / "state"
    for name in ("secrets.db", "secrets.enc", "master.json"):
        if (state / name).exists():
            return True
    return False


def cmd_entry(args):
    msg = (" ".join(args.message)).strip() if args.message else ""
    if msg:
        if msg.startswith("/"):
            cmd_chat(argparse.Namespace(principal="local-cli", model_ref=None, one_shot=msg))
            return
        cmd_chat(argparse.Namespace(principal="local-cli", model_ref=None, one_shot=msg))
        return

    if not _is_onboarded():
        cmd_onboard(argparse.Namespace(master_password=None, llm_provider=None, llm_api_key=None, llm_bot_token=None, gate_bot_token=None, allow_telegram=False, deny_telegram=False, keep_unchanged=False))
        return

    while True:
        choice = input("Choose: onboard | chat | restart | update | factory reset > ").strip().lower()
        if choice == "onboard":
            keep = input("Keep unchanged as default for prompts? [Y/n]: ").strip().lower()
            cmd_onboard(argparse.Namespace(master_password=None, llm_provider=None, llm_api_key=None, llm_bot_token=None, gate_bot_token=None, allow_telegram=False, deny_telegram=False, keep_unchanged=(keep not in {"n", "no"})))
            return
        if choice == "chat":
            cmd_chat(argparse.Namespace(principal="local-cli", model_ref=None, one_shot=None))
            return
        if choice == "restart":
            mp = getpass.getpass("Master password required to restart services: ")
            if not _verify_master_password(mp):
                print("Invalid master password. Restart cancelled.")
                return
            cmd_stop(argparse.Namespace())
            cmd_start(argparse.Namespace())
            print("Services restarted.")
            return
        if choice == "update":
            cmd_update(argparse.Namespace())
            return
        if choice in {"factory reset", "factory-reset"}:
            cmd_reinstall(argparse.Namespace(yes=False))
            return
        print("Unknown choice.")


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

        one_shot = getattr(args, "one_shot", None)
        if one_shot is not None:
            if one_shot.startswith("/"):
                await _send_sheriff(cli_gate, one_shot)
            else:
                await _send_bot(gateway, one_shot)
            print("(waiting up to 10s for additional responses; press Esc to cancel)")
            await asyncio.to_thread(_wait_extra_or_esc, 10)
            return

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
        ob.add_argument("--keep-unchanged", action="store_true", help="When re-onboarding, Enter keeps existing values")

        tg_group = ob.add_mutually_exclusive_group()
        tg_group.add_argument("--allow-telegram", action="store_true", help="Non-interactive: Allow telegram unlock")
        tg_group.add_argument("--deny-telegram", action="store_true", help="Non-interactive: Deny telegram unlock")

        ob.set_defaults(func=cmd_onboard)

    reinstall = sub.add_parser("reinstall")
    reinstall.add_argument("--yes", action="store_true", help="Skip confirmation prompts")
    reinstall.set_defaults(func=cmd_reinstall)

    fr = sub.add_parser("factory-reset")
    fr.add_argument("--yes", action="store_true", help="Skip confirmation prompts")
    fr.set_defaults(func=cmd_reinstall)

    dbg = sub.add_parser("debug")
    dbg.add_argument("value", choices=["on", "off"])
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

def main_sheriff(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="sheriff")
    p.add_argument("--debug", choices=["on", "off"], default=None)
    p.add_argument("message", nargs="*")
    args = p.parse_args(argv)
    if args.debug is not None:
        cmd_debug(argparse.Namespace(value=args.debug))
        return
    cmd_entry(args)
