# File: debug/channel/telegram/telegram_debug.py

import sys
import json
import asyncio
from pathlib import Path

# Add repo root to sys.path
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.proc_rpc import ProcClient
from shared.paths import gw_root

def print_usage():
    print("Usage: sheriff debug channel telegram <command> [args...]")
    print("Commands:")
    print("  user-agent <msg>       Send a message from user to agent")
    print("  agent-user <msg>       Simulate agent sending a message to user")
    print("  user-sheriff <msg>     Send a message from user to sheriff")
    print("  sheriff-user <msg>     Simulate sheriff sending a message to user")
    print("  session <name> <count> Get the last <count> messages from a session")

async def user_agent(msg: str, user_id: str = "debug_user"):
    client = ProcClient("ai-tg-llm")
    print(f"[User -> Agent] {msg}")
    _, res = await client.request("ai_tg_llm.inbound_message", {"user_id": user_id, "text": msg})
    print(f"Result: {json.dumps(res, indent=2)}")

async def user_sheriff(msg: str, user_id: str = "debug_user"):
    client = ProcClient("sheriff-tg-gate")
    print(f"[User -> Sheriff] {msg}")
    _, res = await client.request("gate.inbound_message", {"user_id": user_id, "text": msg})
    print(f"Result: {json.dumps(res, indent=2)}")

def agent_user(msg: str):
    # Simulate agent to user by writing directly to the debug outbox.
    print(f"[Agent -> User] {msg}")
    outbox = gw_root() / "state" / "debug_telegram_outbox.jsonl"
    outbox.parent.mkdir(parents=True, exist_ok=True)
    with open(outbox, "a", encoding="utf-8") as f:
        f.write(json.dumps({"from": "agent", "to": "user", "text": msg}) + "\n")
    print("Message written to debug outbox.")

def sheriff_user(msg: str):
    # Simulate sheriff to user by writing directly to the debug outbox.
    print(f"[Sheriff -> User] {msg}")
    outbox = gw_root() / "state" / "debug_telegram_outbox.jsonl"
    outbox.parent.mkdir(parents=True, exist_ok=True)
    with open(outbox, "a", encoding="utf-8") as f:
        f.write(json.dumps({"from": "sheriff", "to": "user", "text": msg}) + "\n")
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