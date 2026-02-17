from __future__ import annotations

from python_openclaw.gateway.policy import GatewayPolicy
from python_openclaw.gateway.secure_web import SecureWebRequester
from python_openclaw.gateway.secrets.store import SecretStore
from shared.paths import gw_root


class SheriffWebService:
    def __init__(self) -> None:
        root = gw_root()
        policy = GatewayPolicy(allowed_hosts=set(["api.github.com", "github.com"]))
        self.secrets = SecretStore(root / "secrets_service.enc")
        self.requester = SecureWebRequester(policy, self.secrets)

    async def request(self, payload, emit_event, req_id):
        try:
            response = self.requester.request_https(payload)
            return {"status": "executed", "response": response}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    def ops(self):
        return {"web.request": self.request}
