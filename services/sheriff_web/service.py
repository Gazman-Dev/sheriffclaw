from __future__ import annotations

from shared.policy import GatewayPolicy
from shared.proc_rpc import ProcClient
from shared.secure_web import SecureWebRequester


class SheriffWebService:
    def __init__(self) -> None:
        self.requester = SecureWebRequester(GatewayPolicy())
        self.gateway = ProcClient("sheriff-gateway")
        self.policy = ProcClient("sheriff-policy")

    async def _secrets(self, op: str, payload: dict):
        _, res = await self.gateway.request("gateway.secrets.call", {"op": op, "payload": payload})
        return res.get("result", {})

    async def request(self, payload, emit_event, req_id):
        principal_id = payload["principal_id"]
        host = payload["host"]
        _, dec = await self.policy.request("policy.get_decision", {"principal_id": principal_id, "resource_type": "domain", "resource_value": host})
        decision = dec["result"].get("decision")
        if decision != "ALLOW":
            return {"status": "needs_domain_approval", "host": host}

        resolved = {}
        for header, handle in (payload.get("secret_headers") or {}).items():
            sec = await self._secrets("secrets.get_secret", {"handle": handle})
            resolved[header] = sec.get("value", "")
        response = self.requester.request_https(payload, resolved)
        return {"status": "executed", "response": response}

    def ops(self):
        return {"web.request": self.request}
