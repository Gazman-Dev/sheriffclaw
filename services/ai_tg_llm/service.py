from __future__ import annotations

from shared.proc_rpc import ProcClient


class AITgLlmService:
    def __init__(self):
        self.secrets = ProcClient("sheriff-secrets")

    async def ping(self, payload, emit_event, req_id):
        return {"status": "idle"}

    async def inbound_message(self, payload, emit_event, req_id):
        user_id = str(payload.get("user_id", ""))
        text = (payload.get("text") or "").strip()
        role = "llm"

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

    def ops(self):
        return {
            "ai_tg_llm.ping": self.ping,
            "ai_tg_llm.inbound_message": self.inbound_message,
        }
