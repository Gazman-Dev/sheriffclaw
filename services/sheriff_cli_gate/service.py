from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from shared.codex_auth import (
    codex_auth_help_text,
    codex_auth_status,
    codex_device_auth_status,
    finalize_codex_device_auth,
    start_codex_device_auth,
)
from shared.paths import gw_root
from shared.proc_rpc import ProcClient


class SheriffCliGateService:
    def __init__(self) -> None:
        self.requests = ProcClient("sheriff-requests", spawn_fallback=False)
        self.gateway = ProcClient("sheriff-gateway", spawn_fallback=False)
        # Back-compat shim for existing tests/mocks.
        self.secrets = None
        self.services =[
            "sheriff-secrets",
            "sheriff-policy",
            "sheriff-requests",
            "sheriff-web",
            "sheriff-tools",
            "sheriff-gateway",
            "sheriff-tg-gate",
            "sheriff-cli-gate",
            "codex-mcp-host",
            "ai-tg-llm",
        ]
        self.update_pid_path = gw_root() / "state" / "remote_update.pid"

    def _is_pid_running(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _start_remote_update(self, *, no_pull: bool = False, force: bool = False) -> dict[str, str]:
        self.update_pid_path.parent.mkdir(parents=True, exist_ok=True)
        if self.update_pid_path.exists():
            try:
                existing_pid = int(self.update_pid_path.read_text(encoding="utf-8").strip())
            except Exception:
                existing_pid = 0
            if existing_pid and self._is_pid_running(existing_pid):
                return {
                    "ok": False,
                    "message": f"Sheriff update is already running (pid {existing_pid}).",
                }
            self.update_pid_path.unlink(missing_ok=True)

        logs_dir = gw_root() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        out_path = logs_dir / "remote-update.out"
        err_path = logs_dir / "remote-update.err"
        cmd = [sys.executable, "-m", "services.sheriff_ctl.ctl", "update"]
        if no_pull:
            cmd.append("--no-pull")
        if force:
            cmd.append("--force")

        with out_path.open("ab") as out_file, err_path.open("ab") as err_file:
            proc = subprocess.Popen(  # noqa: S603
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=out_file,
                stderr=err_file,
                cwd=str(Path(__file__).resolve().parents[2]),
                start_new_session=True,
            )
        self.update_pid_path.write_text(str(proc.pid), encoding="utf-8")
        return {
            "ok": True,
            "message": (
                f"Sheriff update started in the background (pid {proc.pid}). "
                f"You will get a completion message when it finishes. "
                f"Logs: {out_path.name}, {err_path.name}"
            ),
        }

    async def _secrets(self, op: str, payload: dict):
        if self.secrets is not None:
            _, old = await self.secrets.request(op, payload)
            return old.get("result", {})
        _, res = await self.gateway.request("gateway.secrets.call", {"op": op, "payload": payload})
        outer = res.get("result", {})
        if isinstance(outer, dict) and "result" in outer:
            if not outer.get("ok", True):
                return {}
            inner = outer.get("result", {})
            return inner if isinstance(inner, dict) else {}
        return outer if isinstance(outer, dict) else {}

    async def handle_message(self, payload, emit_event, req_id):
        text = (payload.get("text") or "").strip()
        if not text.startswith("/"):
            return {"kind": "error", "message": "not a sheriff command"}

        parts = text[1:].strip().split()
        if not parts:
            return {
                "kind": "sheriff",
                "message": "Sheriff command received. Try /help.",
            }

        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in {"help", "?"}:
            return {
                "kind": "sheriff",
                "message": (
                    "Sheriff commands:\n"
                    "/status\n"
                    "/update [no-pull] [force]\n"
                    "/auth-status\n"
                    "/auth-login\n"
                    "/unlock <master_password>\n"
                    "/secret <handle> <value>\n"
                    "/deny-secret <handle>\n"
                    "/allow-domain <domain> | /deny-domain <domain>\n"
                    "/allow-tool <tool> | /deny-tool <tool>\n"
                    "/allow-output <key> | /deny-output <key>\n"
                    "Any other /... input is recorded as Sheriff chat."
                ),
            }

        if cmd == "status":
            lines =[]
            for svc in self.services:
                cli = ProcClient(svc, spawn_fallback=False)
                try:
                    _, resp = await cli.request("health", {})
                    st = resp.get("result", {}).get("status", "ok") if resp.get("ok") else "error"
                    lines.append(f"{svc}: {st}")
                except Exception:
                    lines.append(f"{svc}: down")
            return {"kind": "sheriff", "message": "\n".join(lines)}

        if cmd == "unlock":
            if not args:
                return {"kind": "error", "message": "Usage: /unlock <master_password>"}
            mp = " ".join(args)
            res = await self._secrets("secrets.unlock", {"master_password": mp})
            ok = bool(res.get("ok"))
            if ok:
                try:
                    await self.requests.request("requests.submit_master_password", {"master_password": mp})
                except Exception:
                    pass
                return {"kind": "sheriff", "message": "Vault unlocked."}
            return {"kind": "sheriff", "message": "Unlock failed."}

        if cmd == "auth-status":
            status = finalize_codex_device_auth()
            if not status["available"]:
                return {"kind": "sheriff", "message": str(status["detail"])}
            if status["logged_in"]:
                return {"kind": "sheriff", "message": f"Codex auth is active.\n{status['detail']}"}
            device = codex_device_auth_status()
            if device["active"] and device["detail"]:
                return {"kind": "sheriff", "message": str(device["detail"])}
            return {
                "kind": "sheriff",
                "message": f"{status['detail']}\n\n{codex_auth_help_text(interactive_login_supported=False)}",
            }

        if cmd == "auth-login":
            started = start_codex_device_auth()
            return {
                "kind": "sheriff",
                "message": str(started["message"]),
            }

        if cmd == "update":
            no_pull = any(arg.lower() in {"no-pull", "--no-pull"} for arg in args)
            force = any(arg.lower() in {"force", "--force"} for arg in args)
            started = self._start_remote_update(no_pull=no_pull, force=force)
            return {
                "kind": "sheriff",
                "message": str(started["message"]),
            }

        if cmd == "secret":
            if len(args) < 2:
                return {"kind": "error", "message": "Usage: /secret <handle> <value>"}
            handle = args[0]
            value = " ".join(args[1:])
            _, res = await self.requests.request("requests.resolve_secret", {"key": handle, "value": value})
            status = res.get("result", {}).get("status", "unknown")
            return {"kind": "sheriff", "message": f"Secret {handle}: {status}"}

        if cmd == "deny-secret":
            if not args:
                return {"kind": "error", "message": "Usage: /deny-secret <key>"}
            key = " ".join(args)
            _, res = await self.requests.request("requests.resolve_secret", {"key": key, "deny": True})
            status = res.get("result", {}).get("status", "unknown")
            return {"kind": "sheriff", "message": f"Secret {key}: {status}"}

        if cmd in {"allow-domain", "deny-domain", "allow-tool", "deny-tool", "allow-output", "deny-output"}:
            if not args:
                return {"kind": "error", "message": f"Usage: /{cmd} <value>"}
            key = " ".join(args)
            action = "always_allow" if cmd.startswith("allow-") else "deny"
            if cmd.endswith("domain"):
                op = "requests.resolve_domain"
            elif cmd.endswith("tool"):
                op = "requests.resolve_tool"
            else:
                op = "requests.resolve_disclose_output"
            _, res = await self.requests.request(op, {"key": key, "action": action})
            status = res.get("result", {}).get("status", "unknown")
            return {"kind": "sheriff", "message": f"{cmd} {key}: {status}"}

        return {
            "kind": "sheriff",
            "message": f"Sheriff received: {text}",
        }

    def ops(self):
        return {
            "cli.handle_message": self.handle_message,
        }
