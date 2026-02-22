from __future__ import annotations

from shared.proc_rpc import ProcClient


class SheriffCliGateService:
    def __init__(self) -> None:
        self.requests = ProcClient("sheriff-requests")
        self.secrets = ProcClient("sheriff-secrets")
        self.services = [
            "sheriff-secrets",
            "sheriff-policy",
            "sheriff-requests",
            "sheriff-web",
            "sheriff-tools",
            "sheriff-gateway",
            "sheriff-tg-gate",
            "sheriff-cli-gate",
            "ai-worker",
            "ai-tg-llm",
        ]

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
                    "/unlock <master_password>\n"
                    "/secret <handle> <value>\n"
                    "/allow-domain <domain> | /deny-domain <domain>\n"
                    "/allow-tool <tool> | /deny-tool <tool>\n"
                    "/allow-output <key> | /deny-output <key>\n"
                    "Any other /... input is recorded as Sheriff chat."
                ),
            }

        if cmd == "status":
            lines = []
            for svc in self.services:
                cli = ProcClient(svc)
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
            _, res = await self.secrets.request("secrets.unlock", {"master_password": mp})
            ok = bool(res.get("result", {}).get("ok"))
            if ok:
                # compatibility: notify via requests channel so existing UX hooks continue to work
                try:
                    await self.requests.request("requests.submit_master_password", {"master_password": mp})
                except Exception:
                    pass
                return {"kind": "sheriff", "message": "Vault unlocked."}
            return {"kind": "sheriff", "message": "Unlock failed."}

        if cmd == "secret":
            if len(args) < 2:
                return {"kind": "error", "message": "Usage: /secret <handle> <value>"}
            handle = args[0]
            value = " ".join(args[1:])
            _, res = await self.requests.request("requests.resolve_secret", {"key": handle, "value": value})
            status = res.get("result", {}).get("status", "unknown")
            return {"kind": "sheriff", "message": f"Secret {handle}: {status}"}

        # Auth provisioning is intentionally not exposed in Sheriff chat.

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
