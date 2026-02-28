from __future__ import annotations

import requests
from shared.paths import gw_root
from shared.proc_rpc import ProcClient
from shared.transcript import append_jsonl


class SheriffTgGateService:
    def __init__(self):
        self.gateway = ProcClient("sheriff-gateway")
        self.policy = ProcClient("sheriff-policy")
        self.log_path = gw_root() / "state" / "gate_events.jsonl"

    async def _get_bot_token(self) -> str:
        _, res = await self.gateway.request("gateway.secrets.call", {"op": "secrets.get_gate_bot_token", "payload": {}})
        return res.get("result", {}).get("token", "")

    async def _send_telegram(self, text: str):
        token = await self._get_bot_token()
        if not token:
            return

        _, res = await self.gateway.request("gateway.secrets.call", {"op": "secrets.activation.status", "payload": {"bot_role": "sheriff"}})
        user_id = res.get("result", {}).get("user_id")
        if not user_id:
            return

        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": int(user_id), "text": text, "disable_web_page_preview": True},
                timeout=10
            )
        except Exception:
            pass

    async def notify_request(self, payload, emit_event, req_id):
        append_jsonl(self.log_path, payload)

        req_type = payload.get("type", "action")
        key = payload.get("key", "unknown")
        one_liner = payload.get("one_liner", "No description provided.")

        msg = (
            f"🔔 Sheriff Approval Required\n\n"
            f"The agent asks permission to access {req_type}: {key}\n"
            f"Reason: {one_liner}\n\n"
            f"Reply with /allow-{req_type} {key} or /deny-{req_type} {key}"
        )

        await self._send_telegram(msg)
        return {"status": "sent"}

    async def notify_master_password_required(self, payload, emit_event, req_id):
        await self._send_telegram("🔒 Sheriff vault is locked. Please send: /unlock <password>")
        return {"status": "sent"}

    async def notify_master_password_accepted(self, payload, emit_event, req_id):
        await self._send_telegram("✅ Vault unlocked successfully.")
        return {"status": "sent"}

    async def submit_secret(self, payload, emit_event, req_id):
        _, res = await self.gateway.request("gateway.secrets.call", {"op": "secrets.set_secret", "payload": payload})
        return res.get("result", {})

    async def inbound_message(self, payload, emit_event, req_id):
        user_id = str(payload.get("user_id", ""))
        text = (payload.get("text") or "").strip()
        role = "sheriff"

        _, res = await self.gateway.request("gateway.secrets.call", {"op": "secrets.activation.status", "payload": {"bot_role": role}})
        bound = res.get("result", {}).get("user_id")

        if bound and str(bound) == user_id:
            return {"status": "accepted", "user_id": user_id}

        if text.startswith("activate "):
            code = text.split(" ", 1)[1].strip().lower()
            _, claim = await self.gateway.request("gateway.secrets.call", {"op": "secrets.activation.claim", "payload": {"bot_role": role, "code": code}})
            if claim.get("result", {}).get("ok"):
                return {"status": "activated", "user_id": claim["result"]["user_id"]}

        _, c = await self.gateway.request("gateway.secrets.call", {"op": "secrets.activation.create", "payload": {"bot_role": role, "user_id": user_id}})
        code = c.get("result", {}).get("code")
        return {"status": "activation_required", "activation_code": code}

    async def apply_callback(self, payload, emit_event, req_id):
        _, r = await self.policy.request("policy.apply_callback", payload)
        return r["result"]

    def ops(self):
        return {
            "gate.notify_request": self.notify_request,
            "gate.notify_master_password_required": self.notify_master_password_required,
            "gate.notify_master_password_accepted": self.notify_master_password_accepted,
            "gate.submit_secret": self.submit_secret,
            "gate.inbound_message": self.inbound_message,
            "gate.apply_callback": self.apply_callback,
        }