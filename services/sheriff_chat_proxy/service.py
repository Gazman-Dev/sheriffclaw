from __future__ import annotations

import inspect

from shared.proc_rpc import ProcClient


class SheriffChatProxyService:
    def __init__(self) -> None:
        self.gateway = ProcClient("sheriff-gateway", spawn_fallback=False)

    async def send(self, payload, emit_event, req_id):
        stream, final = await self.gateway.request(
            "gateway.handle_user_message",
            {
                "channel": payload.get("channel", "cli"),
                "principal_external_id": payload.get("principal_external_id", "debug-proxy"),
                "text": payload.get("text", ""),
                "model_ref": payload.get("model_ref"),
                "master_password": payload.get("master_password"),
            },
            stream_events=True,
        )
        async for frame in stream:
            await emit_event(frame.get("event", ""), frame.get("payload", {}) or {})
        final_res = await final if inspect.isawaitable(final) else final
        return {"status": "done", "gateway_result": (final_res or {}).get("result", {})}

    async def status(self, payload, emit_event, req_id):
        _, health = await self.gateway.request("health", {})
        _, queue = await self.gateway.request("gateway.queue.status", {})
        return {
            "gateway_health": health.get("result", {}),
            "queue": queue.get("result", {}),
        }

    async def reset(self, payload, emit_event, req_id):
        _, res = await self.gateway.request(
            "gateway.session.reset",
            {"session_id": payload.get("session_id", "primary_session")},
        )
        return res.get("result", {})

    def ops(self):
        return {
            "chatproxy.send": self.send,
            "chatproxy.status": self.status,
            "chatproxy.reset": self.reset,
        }
