from __future__ import annotations

from python_openclaw.gateway.secrets.service import SecretsService
from shared.paths import gw_root


class SheriffSecretsService:
    def __init__(self) -> None:
        root = gw_root()
        self.svc = SecretsService(
            encrypted_path=root / "secrets_service.enc",
            master_verifier_path=root / "master.json",
            telegram_secrets_path=root / "telegram_secrets_channel.json",
        )

    async def initialize(self, payload, emit_event, req_id):
        self.svc.initialize(**payload)
        return {"status": "initialized"}

    async def verify_master(self, payload, emit_event, req_id):
        return {"ok": self.svc.verify_master_password(payload.get("password", ""))}

    async def unlock(self, payload, emit_event, req_id):
        self.svc.unlock(payload["password"])
        return {"status": "unlocked"}

    async def lock(self, payload, emit_event, req_id):
        self.svc.lock()
        return {"status": "locked"}

    async def get_identity(self, payload, emit_event, req_id):
        return {"identity": self.svc.get_identity_state()}

    async def save_identity(self, payload, emit_event, req_id):
        self.svc.save_identity_state(payload.get("identity", {}))
        return {"status": "saved"}

    async def set_secret(self, payload, emit_event, req_id):
        self.svc.set_secret(payload["handle"], payload["value"])
        return {"status": "saved"}

    async def ensure_handle(self, payload, emit_event, req_id):
        return {"ok": self.svc.ensure_handle(payload["handle"])}

    async def get_secret(self, payload, emit_event, req_id):
        return {"value": self.svc.get_secret(payload["handle"])}

    async def get_llm_bot(self, payload, emit_event, req_id):
        return {"token": self.svc.get_llm_bot_token()}

    async def get_gate_bot(self, payload, emit_event, req_id):
        return {"token": self.svc.get_gate_bot_token()}

    async def get_provider(self, payload, emit_event, req_id):
        return {"provider": self.svc.get_provider()}

    async def get_api_key(self, payload, emit_event, req_id):
        return {"api_key": self.svc.get_llm_api_key()}

    def ops(self):
        return {
            "secrets.initialize": self.initialize,
            "secrets.verify_master_password": self.verify_master,
            "secrets.unlock": self.unlock,
            "secrets.lock": self.lock,
            "secrets.get_identity_state": self.get_identity,
            "secrets.save_identity_state": self.save_identity,
            "secrets.set_secret": self.set_secret,
            "secrets.ensure_handle": self.ensure_handle,
            "secrets.get_secret": self.get_secret,
            "secrets.get_llm_bot_token": self.get_llm_bot,
            "secrets.get_gate_bot_token": self.get_gate_bot,
            "secrets.get_llm_provider": self.get_provider,
            "secrets.get_llm_api_key": self.get_api_key,
        }
