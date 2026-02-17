from __future__ import annotations


class AITgLlmService:
    async def ping(self, payload, emit_event, req_id):
        return {"status": "idle"}

    def ops(self):
        return {"ai_tg_llm.ping": self.ping}
