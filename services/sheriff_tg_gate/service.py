from __future__ import annotations

from shared.paths import gw_root
from shared.proc_rpc import ProcClient
from shared.transcript import append_jsonl


class SheriffTgGateService:
    def __init__(self):
        self.secrets = ProcClient("sheriff-secrets")
        self.policy = ProcClient("sheriff-policy")
        self.log_path = gw_root() / "state" / "gate_events.jsonl"

    async def notify_approval_required(self, payload, emit_event, req_id):
        append_jsonl(self.log_path, {"event": "approval_required", **payload})
        return {"status": "logged"}

    async def request_secret(self, payload, emit_event, req_id):
        append_jsonl(self.log_path, {"event": "request_secret", **payload})
        return {"status": "logged"}

    async def notify_request(self, payload, emit_event, req_id):
        append_jsonl(self.log_path, payload)
        return {"status": "logged"}

    async def notify_request_resolved(self, payload, emit_event, req_id):
        append_jsonl(self.log_path, payload)
        return {"status": "logged"}

    async def notify_master_password_required(self, payload, emit_event, req_id):
        append_jsonl(self.log_path, payload)
        return {"status": "logged"}

    async def notify_master_password_accepted(self, payload, emit_event, req_id):
        append_jsonl(self.log_path, payload)
        return {"status": "logged"}

    async def submit_secret(self, payload, emit_event, req_id):
        _, r = await self.secrets.request("secrets.set_secret", {"handle": payload["handle"], "value": payload["value"]})
        return r["result"]

    async def inbound_message(self, payload, emit_event, req_id):
        user_id = str(payload.get("user_id", ""))
        text = (payload.get("text") or "").strip()
        role = "sheriff"

        _, st = await self.secrets.request("secrets.activation.status", {"bot_role": role})
        bound = st.get("result", {}).get("user_id")
        if bound and str(bound) == user_id:
            return {"status": "accepted", "user_id": user_id}

        if text.startswith("activate "):
            code = text.split(" ", 1)[1].strip().lower()
            _, claim = await self.secrets.request("secrets.activation.claim", {"bot_role": role, "code": code})
            if claim.get("result", {}).get("ok"):
                return {"status": "activated", "user_id": claim["result"]["user_id"]}

        _, c = await self.secrets.request("secrets.activation.create", {"bot_role": role, "user_id": user_id})
        code = c.get("result", {}).get("code")
        return {"status": "activation_required", "activation_code": code}

    async def apply_callback(self, payload, emit_event, req_id):
        _, r = await self.policy.request("policy.apply_callback", payload)
        return r["result"]

    def ops(self):
        return {
            "gate.notify_approval_required": self.notify_approval_required,
            "gate.request_secret": self.request_secret,
            "gate.notify_request": self.notify_request,
            "gate.notify_request_resolved": self.notify_request_resolved,
            "gate.notify_master_password_required": self.notify_master_password_required,
            "gate.notify_master_password_accepted": self.notify_master_password_accepted,
            "gate.submit_secret": self.submit_secret,
            "gate.inbound_message": self.inbound_message,
            "gate.apply_callback": self.apply_callback,
        }
