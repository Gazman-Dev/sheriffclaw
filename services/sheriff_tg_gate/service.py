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
            "gate.apply_callback": self.apply_callback,
        }
