from __future__ import annotations

import argparse
import asyncio
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

from services.sheriff_ctl.service_runner import ALL, SERVICE_MANAGER
from services.sheriff_ctl.utils import _gw_secrets_call, _log_paths
from shared.codex_debug import load_config
from shared.paths import agent_root, base_root, gw_root, llm_root
from shared.proc_rpc import ProcClient


def _tail_text(path: Path, max_lines: int) -> str:
    if not path.exists():
        return "(missing)"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return "(empty)"
    return "\n".join(lines[-max_lines:])


def _redact(text: str) -> str:
    text = re.sub(r"\bsk-[A-Za-z0-9_-]+\b", "sk-REDACTED", text)
    text = re.sub(r"\b\d{8,12}:[A-Za-z0-9_-]{20,}\b", "TELEGRAM_TOKEN_REDACTED", text)
    text = re.sub(r"(?i)(master_password|api[_-]?key|token|refresh_token|access_token|id_token)\s*[:=]\s*([^\s\"']+)",
                  r"\1=REDACTED", text)
    return text


async def _health_summary(service: str) -> str:
    cli = ProcClient(service)
    try:
        _, res = await cli.request("health", {})
        result = res.get("result", {})
        return str(result.get("status", "ok"))
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"
    finally:
        await cli.close()


async def _vault_summary() -> str:
    gw = ProcClient("sheriff-gateway")
    try:
        res = await _gw_secrets_call("secrets.is_unlocked", {}, gw=gw)
        return "unlocked" if res.get("unlocked") else "locked"
    except Exception as exc:  # noqa: BLE001
        return f"unknown ({exc})"
    finally:
        await gw.close()


async def _report_async(tail_lines: int) -> str:
    root = base_root()
    agent = agent_root()
    session_root = agent / "conversations" / "sessions"
    latest_session = None
    if session_root.exists():
        dirs = [p for p in session_root.iterdir() if p.is_dir()]
        if dirs:
            latest_session = sorted(dirs, key=lambda p: p.name)[-1]

    lines: list[str] = []
    lines.append("Sheriff Doctor Report")
    lines.append("====================")
    lines.append(f"platform: {platform.platform()}")
    lines.append(f"python: {sys.version.split()[0]}")
    lines.append(f"root: {root}")
    lines.append(f"debug: {os.environ.get('SHERIFF_DEBUG', '0')}")
    lines.append(f"vault: {await _vault_summary()}")
    lines.append("")
    lines.append("Services")
    lines.append("--------")
    for svc in ALL:
        status = SERVICE_MANAGER.status_code(svc)
        health = await _health_summary(svc) if status != "stopped" else "stopped"
        lines.append(f"{svc}: pid={status} health={health}")

    lines.append("")
    lines.append("Codex Debug")
    lines.append("-----------")
    try:
        cfg = load_config()
        lines.append(f"chat_scenario: {cfg.get('chat', 'unknown')}")
        lines.append(f"login_status: {cfg.get('login_status', 'unknown')}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"config_error: {exc}")
    lines.append(f"agent_root: {agent}")
    lines.append(f"gw_root: {gw_root()}")
    lines.append(f"llm_root: {llm_root()}")

    if latest_session is not None:
        lines.append("")
        lines.append("Latest Session")
        lines.append("--------------")
        lines.append(f"session: {latest_session.name}")
        for item in sorted(latest_session.iterdir(), key=lambda p: p.name)[-10:]:
            lines.append(f"{item.name}")
    else:
        lines.append("")
        lines.append("Latest Session")
        lines.append("--------------")
        lines.append("(none)")

    debug_files = [
        llm_root() / "state" / "debug" / "worker_runtime.jsonl",
        llm_root() / "state" / "debug" / "codex_cli_debug.jsonl",
        gw_root() / "state" / "debug" / "codex_debug.json",
        gw_root() / "state" / "transcripts" / "primary_session.jsonl",
    ]
    lines.append("")
    lines.append("Artifacts")
    lines.append("---------")
    for path in debug_files:
        lines.append(f"[{path}]")
        lines.append(_tail_text(path, tail_lines))
        lines.append("")

    key_logs = ["sheriff-gateway", "ai-worker", "telegram-listener", "sheriff-updater"]
    lines.append("Logs")
    lines.append("----")
    for svc in key_logs:
        out_path, err_path = _log_paths(svc)
        lines.append(f"[{svc} stdout: {out_path}]")
        lines.append(_tail_text(out_path, tail_lines))
        lines.append(f"[{svc} stderr: {err_path}]")
        lines.append(_tail_text(err_path, tail_lines))
        lines.append("")

    return _redact("\n".join(lines).strip() + "\n")


def _copy_to_clipboard(text: str) -> tuple[bool, str]:
    candidates: list[list[str]] = []
    if sys.platform == "darwin":
        candidates.append(["pbcopy"])
    elif os.name == "nt":
        candidates.append(["clip"])
    else:
        candidates.extend([["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]])

    for cmd in candidates:
        try:
            subprocess.run(cmd, input=text, text=True, capture_output=True, check=True)  # noqa: S603
            return True, " ".join(cmd)
        except Exception:
            continue
    return False, "clipboard tool not available"


def cmd_doctor(args) -> None:
    report = asyncio.run(_report_async(int(getattr(args, "tail", 40))))
    print(report, end="")
    if getattr(args, "clipboard", False):
        ok, method = _copy_to_clipboard(report)
        if ok:
            print(f"\n[doctor] copied report to clipboard via {method}")
        else:
            print(f"\n[doctor] clipboard copy failed: {method}")


def add_doctor_parser(sub) -> None:
    doc = sub.add_parser("doctor")
    doc.add_argument("--clipboard", action="store_true", help="Copy the doctor report to the system clipboard")
    doc.add_argument("--tail", type=int, default=40, help="Number of trailing lines to include from logs/artifacts")
    doc.set_defaults(func=cmd_doctor)
