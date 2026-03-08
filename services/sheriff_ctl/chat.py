# File: services/sheriff_ctl/chat.py

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import time

from services.sheriff_ctl.onboard import cmd_onboard
from services.sheriff_ctl.service_runner import cmd_start, cmd_stop
from services.sheriff_ctl.system import cmd_factory_reset, cmd_update
from services.sheriff_ctl.utils import _is_onboarded, _verify_master_password, _wait_extra_or_esc_until
from shared.proc_rpc import ProcClient


def cmd_entry(args):
    msg = (" ".join(args.message)).strip() if args.message else ""
    if msg:
        if msg.startswith("/"):
            cmd_chat(argparse.Namespace(principal="local-cli", model_ref=None, one_shot=msg))
            return
        cmd_chat(argparse.Namespace(principal="local-cli", model_ref=None, one_shot=msg))
        return

    if not _is_onboarded():
        cmd_onboard(argparse.Namespace(master_password=None, llm_provider=None, llm_api_key=None, llm_bot_token=None,
                                       gate_bot_token=None, allow_telegram=False, deny_telegram=False,
                                       keep_unchanged=False))
        return

    while True:
        choice = input("Choose: onboard | chat | restart | update | factory reset > ").strip().lower()
        if choice == "onboard":
            keep = input("Keep unchanged as default for prompts? [Y/n]: ").strip().lower()
            cmd_onboard(
                argparse.Namespace(master_password=None, llm_provider=None, llm_api_key=None, llm_bot_token=None,
                                   gate_bot_token=None, allow_telegram=False, deny_telegram=False,
                                   keep_unchanged=(keep not in {"n", "no"})))
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
            cmd_update(argparse.Namespace(master_password=None, no_pull=False))
            return
        if choice in {"factory reset", "factory-reset"}:
            cmd_factory_reset(argparse.Namespace(yes=False))
            return
        print("Unknown choice.")


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

    async def _run():
        nonlocal chat_master_password
        gateway = ProcClient("sheriff-gateway")
        cli_gate = ProcClient("sheriff-cli-gate")

        one_shot = getattr(args, "one_shot", None)
        if one_shot is not None:
            if one_shot.startswith("/"):
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
        print("- Type /reset to reset primary_session")
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
        cli = ProcClient("ai-worker")
        _, resp = await cli.request("skill.main", {"argv": [args.name, *args.argv], "stdin": args.stdin})
        print(resp["result"]["stdout"])

    asyncio.run(_run())
