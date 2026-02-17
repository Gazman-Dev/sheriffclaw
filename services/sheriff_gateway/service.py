from __future__ import annotations

from shared.identity import principal_id_for_channel
from shared.paths import gw_root
from shared.proc_rpc import ProcClient
from shared.transcript import append_jsonl


class SheriffGatewayService:
    def __init__(self) -> None:
        self.ai = ProcClient("ai-worker")
        self.web = ProcClient("sheriff-web")
        self.tools = ProcClient("sheriff-tools")
        self.secrets = ProcClient("sheriff-secrets")
        self.requests = ProcClient("sheriff-requests")
        self.tg_gate = ProcClient("sheriff-tg-gate")
        self.sessions: dict[str, str] = {}

    async def handle_user_message(self, payload, emit_event, req_id):
        channel = payload.get("channel", "cli")
        principal_id = principal_id_for_channel(channel, payload["principal_external_id"])
        text = payload.get("text", "")
        session = self.sessions.get(principal_id)
        if not session:
            _, opened = await self.ai.request("agent.session.open", {"session_id": principal_id})
            session = opened["result"]["session_handle"]
            self.sessions[principal_id] = session

        append_jsonl(gw_root() / "state" / "transcripts" / f"{session.replace(':','_')}.jsonl", {"role": "user", "content": text})
        stream, final = await self.ai.request("agent.session.user_message", {"session_handle": session, "text": text}, stream_events=True)
        async for frame in stream:
            if frame["event"] == "tool.call":
                result = await self._route_tool(principal_id, frame.get("payload", {}))
                await emit_event("tool.result", result)
                await self.ai.request(
                    "agent.session.tool_result",
                    {"session_handle": session, "tool_name": frame["payload"].get("tool_name", "tool"), "result": result},
                )
                continue
            await emit_event(frame["event"], frame.get("payload", {}))
        await final
        return {"status": "done", "session_handle": session}

    async def _route_tool(self, principal_id: str, tool_call: dict) -> dict:
        tool_name = tool_call.get("tool_name")
        payload = tool_call.get("payload", {})
        if tool_name == "secure.web.request":
            _, res = await self.web.request("web.request", {**payload, "principal_id": principal_id})
            return res["result"]
        if tool_name == "tools.exec":
            _, res = await self.tools.request("tools.exec", {**payload, "principal_id": principal_id})
            return res["result"]
        if tool_name == "secure.secret.ensure":
            _, res = await self.secrets.request("secrets.ensure_handle", payload)
            if res["result"].get("ok"):
                return {"status": "available"}
            return {"status": "needs_secret", "handle": payload.get("handle")}
        if tool_name.startswith("requests."):
            _, res = await self.requests.request(tool_name, payload)
            return res["result"]
        return {"status": "error", "error": f"unsupported tool {tool_name}"}

    async def notify_request_resolved(self, payload, emit_event, req_id):
        if not self.sessions:
            return {"status": "no_session"}
        session_handle = next(reversed(self.sessions.values()))
        result = {"type": payload.get("type"), "key": payload.get("key"), "status": payload.get("status")}
        await self.ai.request(
            "agent.session.tool_result",
            {"session_handle": session_handle, "tool_name": "requests.resolved", "result": result},
        )
        append_jsonl(
            gw_root() / "state" / "transcripts" / f"{session_handle.replace(':','_')}.jsonl",
            {"role": "tool", "name": "requests.resolved", "content": result},
        )
        return {"status": "notified", "session_handle": session_handle}

    def ops(self):
        return {
            "gateway.handle_user_message": self.handle_user_message,
            "gateway.notify_request_resolved": self.notify_request_resolved,
        }
