# File: services/sheriff_ctl/chat.py

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
import time

from services.sheriff_ctl.onboard import cmd_onboard
from services.sheriff_ctl.utils import _is_onboarded, _wait_extra_or_esc_until
from shared.errors import ServiceCrashedError
from shared.proc_rpc import ProcClient


DEFAULT_CHAT_PRINCIPAL = "main"
SECRET_HANDLES_RE = re.compile(r"^[A-Z_][A-Z0-9_]*(\s*,\s*[A-Z_][A-Z0-9_]*)*$")
CHAT_REQUEST_TIMEOUT_SEC = 90.0


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


def maybe_parse_wrapped_command(argv: list[str]) -> dict | None:
    if len(argv) < 3:
        return None
    command = str(argv[0]).strip()
    handles_raw = str(argv[1]).strip()
    if not command or shutil.which(command) is None:
        return None
    if not SECRET_HANDLES_RE.fullmatch(handles_raw):
        return None
    handles = [item.strip() for item in handles_raw.split(",") if item.strip()]
    if not handles or len(argv) < 3:
        return None
    return {"argv": [command, *argv[2:]], "env_handles": handles}


def cmd_wrapped_command(args):
    async def _run() -> int:
        cli = ProcClient("sheriff-tools")
        cli.request_timeout_sec = CHAT_REQUEST_TIMEOUT_SEC
        _, res = await cli.request(
            "tools.exec",
            {
                "principal_id": "default",
                "argv": args.argv,
                "env_handles": args.env_handles,
            },
        )
        result = res.get("result", {})
        status = result.get("status")
        if status == "executed":
            stdout = result.get("stdout") or ""
            stderr = result.get("stderr") or ""
            if stdout:
                print(stdout, end="")
            if stderr:
                print(stderr, end="", file=sys.stderr)
            return int(result.get("code", 1))
        if status == "needs_secret":
            handles = ", ".join(result.get("missing_handles") or args.env_handles)
            print(
                f"Sheriff is missing secret handle(s): {handles}. A request was sent to the user.",
                file=sys.stderr,
            )
            return 3
        if status == "master_password_required":
            print("Sheriff vault is locked. Unlock it first.", file=sys.stderr)
            return 4
        if status == "needs_tool_approval":
            print(
                f'Sheriff needs approval to run tool "{result.get("tool")}". '
                f'Wait for approval or use /allow-tool {result.get("tool")}.',
                file=sys.stderr,
            )
            return 5
        print(f"Sheriff command failed: {json.dumps(result, ensure_ascii=False)}", file=sys.stderr)
        return 1

    raise SystemExit(asyncio.run(_run()))


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
        gateway.request_timeout_sec = CHAT_REQUEST_TIMEOUT_SEC
        cli_gate = ProcClient("sheriff-cli-gate")

        one_shot = getattr(args, "one_shot", None)
        if one_shot is not None:
            try:
                if one_shot.startswith("/"):
                    last_activity = await _send_sheriff(cli_gate, one_shot)
                else:
                    last_activity = await _send_bot(gateway, one_shot)
            except ServiceCrashedError as e:
                msg = str(e)
                if "timeout" in msg.lower():
                    print("[AGENT] Request timed out before the agent completed.")
                else:
                    print(f"[AGENT] Internal system error: {msg}")
                return
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
                try:
                    await _send_bot(gateway, text)
                except ServiceCrashedError as e:
                    msg = str(e)
                    if "timeout" in msg.lower():
                        print("[AGENT] Request timed out before the agent completed.")
                    else:
                        print(f"[AGENT] Internal system error: {msg}")

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
