from __future__ import annotations

import json

from shared.paths import gw_root
from shared.policy import GatewayPolicy
from shared.proc_rpc import ProcClient
from shared.secure_web import SecureWebRequester


class SheriffWebService:
    def __init__(self) -> None:
        cfg_path = gw_root() / "state" / "config.json"
        allowed = {"api.github.com"}
        if cfg_path.exists():
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            allowed = set(data.get("allowed_hosts", ["api.github.com"]))
        self.requester = SecureWebRequester(GatewayPolicy(allowed))
        self.secrets = ProcClient("sheriff-secrets")
        self.policy = ProcClient("sheriff-policy")

    async def request(self, payload, emit_event, req_id):
        principal_id = payload["principal_id"]
        host = payload["host"]
        _, dec = await self.policy.request("policy.get_decision", {"principal_id": principal_id, "resource_type": "domain", "resource_value": host})
        decision = dec["result"].get("decision")
        if decision != "ALLOW":
            _, apr = await self.policy.request(
                "policy.request_permission",
                {"principal_id": principal_id, "resource_type": "domain", "resource_value": host, "metadata": {"op": "web.request"}},
            )
            return {"status": "approval_requested", "approval_id": apr["result"]["approval_id"], "resource": {"type": "domain", "value": host}}

        resolved = {}
        for header, handle in (payload.get("secret_headers") or {}).items():
            _, sec = await self.secrets.request("secrets.get_secret", {"handle": handle})
            resolved[header] = sec["result"].get("value", "")
        response = self.requester.request_https(payload, resolved)
        return {"status": "executed", "response": response}

    def ops(self):
        return {"web.request": self.request}
