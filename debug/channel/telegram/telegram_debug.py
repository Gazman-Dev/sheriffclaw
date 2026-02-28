# File: debug/channel/telegram/telegram_debug.py

import asyncio
import json
import sys
from pathlib import Path

# Add repo root to sys.path
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.paths import gw_root
from shared.proc_rpc import ProcClient


def _append_outbox(entry: dict) -> None:
    outbox = gw_root() / "state" / "debug" / "telegram_outbox.jsonl"
    outbox.parent.mkdir(parents=True, exist_ok=True)
    with outbox.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def print_usage():
    print("Usage: sheriff debug channel telegram <command> [args...]")
    print("Commands:")
    print("  user-agent <msg>       Send a message from user to agent")
    print("  agent-user <msg>       Simulate agent sending a message to user")
    print("  user-sheriff <msg>     Send a message from user to sheriff")
    print("  sheriff-user <msg>     Simulate sheriff sending a message to user")
    print("  session <name> <count> Get the last <count> messages from a session")


async def user_agent(msg: str, user_id: str = "debug_user"):
    text = (msg or "").strip()
    if text.lower().startswith("scenario secret "):
        handle = text.split(" ", 2)[2].strip() if len(text.split(" ", 2)) > 2 else ""
        req = ProcClient("sheriff-requests")
        _, res = await req.request(
            "requests.create_or_update",
            {"type": "secret", "key": handle, "one_liner": f"Need secret {handle}",
             "context": {"source": "debug.telegram"}},
        )
        _append_outbox(
            {"from": "agent", "to": user_id, "text": f"Requested secret {handle}. Please approve it in Sheriff."})
        print(f"[User -> Agent] {msg}")
        print(f"Result: {json.dumps(res, indent=2)}")
        return

    if text.lower().startswith("scenario last tool"):
        gw = ProcClient("sheriff-gateway")
        _, res = await gw.request(
            "gateway.secrets.call",
            {"op": "secrets.ensure_handle", "payload": {"handle": "gh_token"}},
        )
        outer = res.get("result", {}) if isinstance(res, dict) else {}
        inner = outer.get("result", {}) if isinstance(outer, dict) else {}
        status = "approved" if bool(inner.get("ok")) else "needs_secret"
        _append_outbox({"from": "agent", "to": user_id, "text": f"Tool result acknowledged: {status} (gh_token)."})
        print(f"[User -> Agent] {msg}")
        print(f"Result: {json.dumps(res, indent=2)}")
        return

    client = ProcClient("sheriff-gateway")
    print(f"[User -> Agent] {msg}")
    stream, final = await client.request(
        "gateway.handle_user_message",
        {"channel": "telegram", "principal_external_id": user_id, "text": msg},
        stream_events=True,
    )
    reply = None
    async for frame in stream:
        if frame.get("event") == "assistant.final":
            reply = str((frame.get("payload") or {}).get("text") or "")
    final_res = await final
    if reply:
        _append_outbox({"from": "agent", "to": user_id, "text": reply})
    print(f"Result: {json.dumps(final_res, indent=2)}")


async def user_sheriff(msg: str, user_id: str = "debug_user"):
    print(f"[User -> Sheriff] {msg}")
    text = (msg or "").strip()
    if text.lower().startswith("/unlock "):
        pw = text.split(" ", 1)[1].strip()
        gw = ProcClient("sheriff-gateway")
        _, res = await gw.request("gateway.secrets.call", {"op": "secrets.unlock", "payload": {"master_password": pw}})
        outer = res.get("result", {}) if isinstance(res, dict) else {}
        inner = outer.get("result", {}) if isinstance(outer, dict) else {}
        ok = bool(inner.get("ok"))
        out_text = "Vault unlocked." if ok else "Unlock failed."
        _append_outbox({"from": "sheriff", "to": user_id, "text": out_text})
        print(f"Result: {json.dumps(res, indent=2)}")
        return

    cli = ProcClient("sheriff-cli-gate")
    _, out = await cli.request("cli.handle_message", {"text": text})
    payload = out.get("result", {}) if isinstance(out, dict) else {}
    out_text = str(payload.get("message") or "")
    if out_text:
        _append_outbox({"from": "sheriff", "to": user_id, "text": out_text})
    print(f"Result: {json.dumps(out, indent=2)}")


def agent_user(msg: str):
    print(f"[Agent -> User] {msg}")
    _append_outbox({"from": "agent", "to": "user", "text": msg})
    print("Message written to debug outbox.")


def sheriff_user(msg: str):
    print(f"[Sheriff -> User] {msg}")
    _append_outbox({"from": "sheriff", "to": "user", "text": msg})
    print("Message written to debug outbox.")


def session_history(session_name: str, count: int):
    path = gw_root() / "state" / "transcripts" / f"{session_name}.jsonl"
    if not path.exists():
        print(f"Session '{session_name}' not found.")
        return

    lines = path.read_text(encoding="utf-8").strip().split("\n")
    lines = [l for l in lines if l]
    recent = lines[-count:] if count > 0 else lines

    print(f"--- Last {len(recent)} messages from {session_name} ---")
    for line in recent:
        try:
            obj = json.loads(line)
            role = obj.get("role", "unknown")
            content = obj.get("content", "")
            if isinstance(content, dict):
                content = json.dumps(content)
            print(f"[{role.upper()}] {content}")
        except Exception:
            print(line)


def main():
    args = sys.argv[1:]
    if not args:
        print_usage()
        sys.exit(1)

    cmd = args[0]

    if cmd == "user-agent":
        asyncio.run(user_agent(" ".join(args[1:])))
    elif cmd == "user-sheriff":
        asyncio.run(user_sheriff(" ".join(args[1:])))
    elif cmd == "agent-user":
        agent_user(" ".join(args[1:]))
    elif cmd == "sheriff-user":
        sheriff_user(" ".join(args[1:]))
    elif cmd == "session":
        if len(args) < 3:
            print("Usage: session <name> <count>")
            sys.exit(1)
        session_history(args[1], int(args[2]))
    else:
        print(f"Unknown command: {cmd}")
        print_usage()


if __name__ == "__main__":
    main()
