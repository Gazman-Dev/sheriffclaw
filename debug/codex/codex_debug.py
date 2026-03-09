from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.codex_debug import load_config, reset_config, save_config
from shared.paths import llm_root


def _workspace_root() -> Path:
    home = (Path.cwd() if not sys.argv else None)
    env_home = None
    try:
        import os

        env_home = os.environ.get("CODEX_HOME")
    except Exception:
        env_home = None
    if env_home:
        return Path(env_home)
    if home is not None:
        return home
    return Path.cwd()


def _debug_log(event: str, **payload) -> None:
    path = llm_root() / "state" / "debug" / "codex_cli_debug.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"event": event, **payload}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _iter_new_user_files(seen: set[str], sessions_root: Path):
    if not sessions_root.exists():
        return []
    fresh = []
    for session_dir in sorted(p for p in sessions_root.iterdir() if p.is_dir()):
        for user_file in sorted(session_dir.glob("*_user_agent.tmd")):
            key = str(user_file.resolve())
            if key in seen:
                continue
            try:
                user_ts = int(user_file.name.split("_", 1)[0])
            except Exception:
                user_ts = 0
            responded = False
            for agent_file in session_dir.glob("*_agent_user.tmd"):
                try:
                    agent_ts = int(agent_file.name.split("_", 1)[0])
                except Exception:
                    continue
                if agent_ts >= user_ts:
                    responded = True
                    break
            if responded:
                seen.add(key)
                continue
            seen.add(key)
            fresh.append((session_dir, user_file))
    return fresh


def _write_pending(session_dir: Path, text: str) -> None:
    typing_file = session_dir / "agent_user_typing.tmd"
    typing_file.unlink(missing_ok=True)
    (session_dir / "agent_user_pending.tmd").write_text(text, encoding="utf-8")


def _handle_chat_message(session_dir: Path, user_file: Path, chat_mode: str) -> None:
    text = user_file.read_text(encoding="utf-8").strip()
    _debug_log("chat_message", session=str(session_dir.name), file=user_file.name, mode=chat_mode, text=text)
    typing_file = session_dir / "agent_user_typing.tmd"

    if chat_mode == "timeout":
        return
    if chat_mode == "typing_timeout":
        typing_file.touch()
        return
    if chat_mode == "delayed_success":
        typing_file.touch()
        time.sleep(0.4)
    elif chat_mode == "success":
        typing_file.unlink(missing_ok=True)

    _write_pending(session_dir, f"Debug Codex Response to: {text}")


def run_chat() -> int:
    workspace = _workspace_root()
    sessions_root = workspace / "conversations" / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)
    seen = set()
    _debug_log("chat_start", workspace=str(workspace), sessions_root=str(sessions_root))

    try:
        while True:
            cfg = load_config()
            for session_dir, user_file in _iter_new_user_files(seen, sessions_root):
                _handle_chat_message(session_dir, user_file, cfg.get("chat", "success"))
            time.sleep(0.1)
    except KeyboardInterrupt:
        _debug_log("chat_stop", reason="keyboard_interrupt")
        return 0


def run_login_status() -> int:
    cfg = load_config()
    login_status = cfg.get("login_status", "ok")
    _debug_log("login_status", status=login_status)
    return 0 if login_status == "ok" else 1


def print_usage() -> None:
    print("Usage:")
    print("  codex_debug.py chat")
    print("  codex_debug.py login status")
    print("  codex_debug.py <success|timeout|typing-timeout|delayed-success|login-ok|login-missing|show|clear>")


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if not args:
        print_usage()
        return 1

    if args[0] == "chat":
        return run_chat()

    if args[:2] == ["login", "status"]:
        return run_login_status()

    if args[0] == "show":
        print(json.dumps(load_config(), ensure_ascii=False, indent=2))
        return 0

    if args[0] == "clear":
        print(json.dumps(reset_config(), ensure_ascii=False, indent=2))
        return 0

    config = load_config()
    if args[0] == "success":
        config["chat"] = "success"
    elif args[0] == "timeout":
        config["chat"] = "timeout"
    elif args[0] == "typing-timeout":
        config["chat"] = "typing_timeout"
    elif args[0] == "delayed-success":
        config["chat"] = "delayed_success"
    elif args[0] == "login-ok":
        config["login_status"] = "ok"
    elif args[0] == "login-missing":
        config["login_status"] = "missing"
    else:
        print_usage()
        return 1

    print(json.dumps(save_config(config), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
