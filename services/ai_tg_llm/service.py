from __future__ import annotations

from shared.proc_rpc import ProcClient


class AITgLlmService:
    def __init__(self):
        self.gateway = ProcClient("sheriff-gateway")

    async def _secrets(self, op: str, payload: dict):
        _, res = await self.gateway.request("gateway.secrets.call", {"op": op, "payload": payload})
        outer = res.get("result", {})
        if isinstance(outer, dict) and "result" in outer:
            if not outer.get("ok", True):
                return {}
            inner = outer.get("result", {})
            return inner if isinstance(inner, dict) else {}
        return outer if isinstance(outer, dict) else {}

    async def ping(self, payload, emit_event, req_id):
        return {"status": "idle"}

    async def inbound_message(self, payload, emit_event, req_id):
        user_id = str(payload.get("user_id", ""))
        text = (payload.get("text") or "").strip()
        role = "llm"

        st = await self._secrets("secrets.activation.status", {"bot_role": role})
        # If vault is locked/unavailable, activation lookup may be inaccessible.
        # Fall back to gateway lock handling so user still gets a response.
        if not st or "user_id" not in st:
            return {"status": "accepted", "user_id": user_id, "degraded": "activation_unavailable"}

        bound = st.get("user_id")
        if bound and str(bound) == user_id:
            return {"status": "accepted", "user_id": user_id}

        if text.startswith("activate "):
            code = text.split(" ", 1)[1].strip().lower()
            claim = await self._secrets("secrets.activation.claim", {"bot_role": role, "code": code})
            if claim.get("ok"):
                return {"status": "activated", "user_id": claim["user_id"]}

        c = await self._secrets("secrets.activation.create", {"bot_role": role, "user_id": user_id})
        code = c.get("code")
        return {"status": "activation_required", "activation_code": code}

    def ops(self):
        return {
            "ai_tg_llm.ping": self.ping,
            "ai_tg_llm.inbound_message": self.inbound_message,
        }
