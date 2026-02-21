from __future__ import annotations

from shared.paths import gw_root
from shared.secrets_state import SecretsState


class SheriffSecretsService:
    def __init__(self) -> None:
        state_dir = gw_root() / "state"
        self.state = SecretsState(state_dir / "secrets.enc", state_dir / "master.json")

    async def initialize(self, payload, emit_event, req_id):
        self.state.initialize(payload)
        return {"status": "initialized"}

    async def verify_master(self, payload, emit_event, req_id):
        return {"ok": self.state.verify_master_password(payload["master_password"])}

    async def unlock(self, payload, emit_event, req_id):
        return {"ok": self.state.unlock(payload["master_password"])}

    async def lock(self, payload, emit_event, req_id):
        self.state.lock()
        return {"status": "locked"}

    async def is_unlocked(self, payload, emit_event, req_id):
        return {"unlocked": self.state.is_unlocked()}

    async def get_secret(self, payload, emit_event, req_id):
        return {"value": self.state.get_secret(payload["handle"])}

    async def set_secret(self, payload, emit_event, req_id):
        self.state.set_secret(payload["handle"], payload["value"])
        return {"status": "saved"}

    async def ensure_handle(self, payload, emit_event, req_id):
        return {"ok": self.state.ensure_handle(payload["handle"])}

    async def get_llm_provider(self, payload, emit_event, req_id):
        return {"provider": self.state.get_llm_provider()}

    async def get_llm_api_key(self, payload, emit_event, req_id):
        return {"api_key": self.state.get_llm_api_key()}

    async def set_llm_provider(self, payload, emit_event, req_id):
        self.state.set_llm_provider(payload.get("provider", "stub"))
        return {"status": "saved"}

    async def set_llm_api_key(self, payload, emit_event, req_id):
        self.state.set_llm_api_key(payload.get("api_key", ""))
        return {"status": "saved"}

    async def get_llm_auth(self, payload, emit_event, req_id):
        return {"auth": self.state.get_llm_auth()}

    async def set_llm_auth(self, payload, emit_event, req_id):
        self.state.set_llm_auth(payload.get("auth", {}))
        return {"status": "saved"}

    async def clear_llm_auth(self, payload, emit_event, req_id):
        self.state.clear_llm_auth()
        return {"status": "cleared"}

    async def get_llm_bot_token(self, payload, emit_event, req_id):
        return {"token": self.state.get_llm_bot_token()}

    async def set_llm_bot_token(self, payload, emit_event, req_id):
        self.state.set_llm_bot_token(payload.get("token", ""))
        return {"status": "saved"}

    async def get_gate_bot_token(self, payload, emit_event, req_id):
        return {"token": self.state.get_gate_bot_token()}

    async def set_gate_bot_token(self, payload, emit_event, req_id):
        self.state.set_gate_bot_token(payload.get("token", ""))
        return {"status": "saved"}

    async def identity_get(self, payload, emit_event, req_id):
        return self.state.get_identity()

    async def identity_save(self, payload, emit_event, req_id):
        self.state.save_identity(payload)
        return {"status": "saved"}

    async def activation_create(self, payload, emit_event, req_id):
        code = self.state.create_activation_code(payload["bot_role"], str(payload["user_id"]))
        return {"code": code}

    async def activation_claim(self, payload, emit_event, req_id):
        user_id = self.state.activate_with_code(payload["bot_role"], payload["code"])
        return {"ok": bool(user_id), "user_id": user_id}

    async def activation_status(self, payload, emit_event, req_id):
        return {"user_id": self.state.get_bound_user(payload["bot_role"]) }

    async def telegram_webhook_get(self, payload, emit_event, req_id):
        return {"config": self.state.get_telegram_webhook_config()}

    async def telegram_webhook_set(self, payload, emit_event, req_id):
        self.state.set_telegram_webhook_config(payload.get("config", {}))
        return {"status": "saved"}

    def ops(self):
        return {
            "secrets.initialize": self.initialize,
            "secrets.verify_master_password": self.verify_master,
            "secrets.unlock": self.unlock,
            "secrets.lock": self.lock,
            "secrets.is_unlocked": self.is_unlocked,
            "secrets.get_llm_bot_token": self.get_llm_bot_token,
            "secrets.set_llm_bot_token": self.set_llm_bot_token,
            "secrets.get_gate_bot_token": self.get_gate_bot_token,
            "secrets.set_gate_bot_token": self.set_gate_bot_token,
            "secrets.get_llm_provider": self.get_llm_provider,
            "secrets.get_llm_api_key": self.get_llm_api_key,
            "secrets.set_llm_provider": self.set_llm_provider,
            "secrets.set_llm_api_key": self.set_llm_api_key,
            "secrets.get_llm_auth": self.get_llm_auth,
            "secrets.set_llm_auth": self.set_llm_auth,
            "secrets.clear_llm_auth": self.clear_llm_auth,
            "secrets.get_secret": self.get_secret,
            "secrets.set_secret": self.set_secret,
            "secrets.ensure_handle": self.ensure_handle,
            "secrets.identity.get": self.identity_get,
            "secrets.identity.save": self.identity_save,
            "secrets.activation.create": self.activation_create,
            "secrets.activation.claim": self.activation_claim,
            "secrets.activation.status": self.activation_status,
            "secrets.telegram_webhook.get": self.telegram_webhook_get,
            "secrets.telegram_webhook.set": self.telegram_webhook_set,
        }
