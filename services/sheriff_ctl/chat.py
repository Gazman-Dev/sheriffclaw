# File: services/sheriff_ctl/chat.py

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time

from services.sheriff_ctl.onboard import cmd_onboard
from services.sheriff_ctl.utils import _is_onboarded, _wait_extra_or_esc_until
from shared.codex_auth import codex_auth_env, codex_auth_status
from shared.proc_rpc import ProcClient


DEFAULT_CHAT_PRINCIPAL = "main"


def cmd_entry(args):
    msg = (" ".join(args.message)).strip() if args.message else ""
    if msg:
        if msg.startswith("/"):
            cmd_chat(argparse.Namespace(principal=DEFAULT_CHAT_PRINCIPAL, model_ref=None, one_shot=msg))
            return
        cmd_chat(argparse.Namespace(principal=DEFAULT_CHAT_PRINCIPAL, model_ref=None, one_shot=msg))
        return

    if not _is_onboarded():
        cmd_onboard(argparse.Namespace(master_password=None, llm_provider=None, llm_api_key=None, llm_bot_token=None,
                                       gate_bot_token=None, allow_telegram=False, deny_telegram=False,
                                       keep_unchanged=False))
        return

    cmd_chat(argparse.Namespace(principal=DEFAULT_CHAT_PRINCIPAL, model_ref=None, one_shot=None))


def cmd_chat(args):
    principal = args.principal
    model_ref = args.model_ref
    chat_master_password = None

    async def _send_bot(gateway: ProcClient, text: str) -> float:
        payload = {"channel": "cli", "principal_external_id": principal, "text": text, "model_ref": model_ref}
        if chat_master_password:
            payload["master_password"] = chat_master_password
        stream, final = await gateway.request(
            "gateway.handle_user_message",
            payload,
            stream_events=True,
        )
        bot_printed = False
        last_activity = time.time()
        async for frame in stream:
            event = frame.get("event")
            payload = frame.get("payload", {})
            if event == "assistant.delta":
                print(f"[AGENT] {payload.get('text', '')}")
                bot_printed = True
                last_activity = time.time()
            elif event == "assistant.final" and not bot_printed:
                print(f"[AGENT] {payload.get('text', '')}")
                bot_printed = True
                last_activity = time.time()
            elif event == "tool.result":
                print(f"[TOOL] {json.dumps(payload, ensure_ascii=False)}")
                last_activity = time.time()
        await final
        return last_activity

    async def _send_sheriff(cli_gate: ProcClient, text: str) -> float:
        _, res = await cli_gate.request("cli.handle_message", {"text": text})
        msg = res.get("result", {}).get("message", "")
        kind = res.get("result", {}).get("kind", "sheriff").upper()
        print(f"[{kind}] {msg}")
        return time.time()

    async def _run_local_auth_login() -> float:
        status = codex_auth_status()
        if not status["available"]:
            print(f"[SHERIFF] {status['detail']}")
            return time.time()
        if status["logged_in"]:
            print("[SHERIFF] Codex auth is already active for this Sheriff repo.")
            return time.time()

        print("[SHERIFF] Starting local Codex login for this Sheriff repo...")
        login = await asyncio.to_thread(subprocess.run, ["codex", "login"], env=codex_auth_env(), check=False)
        if login.returncode != 0:
            print("[SHERIFF] Codex login did not complete successfully.")
            return time.time()

        refreshed = codex_auth_status()
        if refreshed["logged_in"]:
            print("[SHERIFF] Codex auth is now active.")
        else:
            print(f"[SHERIFF] Login finished but auth is still not active.\n{refreshed['detail']}")
        return time.time()

    async def _run():
        nonlocal chat_master_password
        gateway = ProcClient("sheriff-gateway")
        cli_gate = ProcClient("sheriff-cli-gate")

        one_shot = getattr(args, "one_shot", None)
        if one_shot is not None:
            if one_shot.lower() == "/auth-login":
                last_activity = await _run_local_auth_login()
            elif one_shot.startswith("/"):
                last_activity = await _send_sheriff(cli_gate, one_shot)
            else:
                last_activity = await _send_bot(gateway, one_shot)
            print("(waiting 10s after last response; press Esc to cancel)")
            await asyncio.to_thread(_wait_extra_or_esc_until, last_activity + 10)
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
                if text.lower().startswith("/unlock "):
                    chat_master_password = text.split(" ", 1)[1].strip() or None
                if text.lower() == "/auth-login":
                    await _run_local_auth_login()
                else:
                    await _send_sheriff(cli_gate, text)
            else:
                await _send_bot(gateway, text)

    asyncio.run(_run())


def cmd_proxy_chat(args):
    principal = args.principal
    model_ref = args.model_ref
    chat_master_password = None

    async def _send(proxy: ProcClient, text: str) -> float:
        payload = {"channel": "cli", "principal_external_id": principal, "text": text, "model_ref": model_ref}
        if chat_master_password:
            payload["master_password"] = chat_master_password
        stream, final = await proxy.request("chatproxy.send", payload, stream_events=True)
        last_activity = time.time()
        async for frame in stream:
            event = frame.get("event")
            payload = frame.get("payload", {})
            if event in {"assistant.delta", "assistant.final"}:
                print(f"[AGENT] {payload.get('text', '')}")
                last_activity = time.time()
            elif event == "tool.result":
                print(f"[TOOL] {json.dumps(payload, ensure_ascii=False)}")
                last_activity = time.time()
            else:
                print(json.dumps(frame, ensure_ascii=False))
                last_activity = time.time()
        await final
        return last_activity

    async def _run():
        nonlocal chat_master_password
        proxy = ProcClient("sheriff-chat-proxy")
        one_shot = getattr(args, "one_shot", None)
        if one_shot is not None:
            await _send(proxy, one_shot)
            return

        print("SheriffClaw proxy chat")
        print("- Sends messages through sheriff-chat-proxy")
        print("- Type /reset to reset private_main")
        print("- Type /status to inspect proxy status")
        print("- Type /quit or /exit to leave")
        while True:
            try:
                line = await asyncio.to_thread(input, "proxy> ")
            except (EOFError, KeyboardInterrupt):
                print("\nbye")
                return
            text = line.rstrip("\n")
            if not text:
                continue
            if text in {"/quit", "/exit"}:
                print("bye")
                return
            if text == "/status":
                _, res = await proxy.request("chatproxy.status", {})
                print(json.dumps(res.get("result", {}), ensure_ascii=False, indent=2))
                continue
            if text == "/reset":
                _, res = await proxy.request("chatproxy.reset", {})
                print(json.dumps(res.get("result", {}), ensure_ascii=False))
                continue
            if text.lower().startswith("/unlock "):
                chat_master_password = text.split(" ", 1)[1].strip() or None
            await _send(proxy, text)

    asyncio.run(_run())


def cmd_call(args):
    async def _run():
        cli = ProcClient(args.service)
        stream, final = await cli.request(args.op, json.loads(args.json), stream_events=True)
        async for frame in stream:
            print(json.dumps(frame, ensure_ascii=False))
        print(json.dumps(await final, ensure_ascii=False))

    asyncio.run(_run())


def cmd_skill(args):
    async def _run():
        cli = ProcClient("codex-mcp-host")
        _, resp = await cli.request("skill.main", {"argv": [args.name, *args.argv], "stdin": args.stdin})
        print(resp["result"]["stdout"])

    asyncio.run(_run())
