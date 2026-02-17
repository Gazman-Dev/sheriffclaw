from __future__ import annotations

import json
from pathlib import Path

from shared.paths import gw_root
from shared.proc_rpc import ProcClient


class SheriffGatewayService:
    def __init__(self) -> None:
        root = gw_root()
        self.transcripts = root / "transcripts"
        self.transcripts.mkdir(parents=True, exist_ok=True)
        self.ai = ProcClient("ai-worker")
        self.web = ProcClient("sheriff-web")
        self.tools = ProcClient("sheriff-tools")
        self.secrets = ProcClient("sheriff-secrets")
        self.policy = ProcClient("sheriff-policy")
        self.session_by_principal: dict[str, str] = {}

    async def handle_user_message(self, payload, emit_event, req_id):
        principal = payload["principal_external_id"]
        text = payload.get("text", "")
        session = self.session_by_principal.get(principal)
        if not session:
            _, opened = await self.ai.request("agent.session.open", {"session_id": f"{payload.get('channel','cli')}:{principal}"})
            session = opened["result"]["session_handle"]
            self.session_by_principal[principal] = session

        self._append_transcript(session, {"role": "user", "content": text})
        stream, final_fut = await self.ai.request("agent.session.user_message", {"session_handle": session, "text": text}, stream_events=True)
        async for frame in stream:
            event = frame["event"]
            event_payload = frame.get("payload", {})
            if event == "tool.call":
                tool_result = await self._route_tool(principal, event_payload)
                await emit_event("tool.result", tool_result)
                await self.ai.request("agent.session.tool_result", {"session_handle": session, "tool_name": event_payload.get("tool_name", "tool"), "result": tool_result})
                continue
            await emit_event(event, event_payload)
        await final_fut
        return {"status": "done", "session_handle": session}

    async def _route_tool(self, principal: str, call: dict) -> dict:
        name = call.get("tool_name")
        payload = call.get("payload", {})
        if name == "secure.web.request":
            _, resp = await self.web.request("web.request", payload)
            return resp.get("result", resp)
        if name == "tools.exec":
            payload = {**payload, "principal_id": principal}
            _, resp = await self.tools.request("tools.exec", payload)
            return resp.get("result", resp)
        if name == "secure.secret.ensure":
            _, resp = await self.secrets.request("secrets.ensure_handle", payload)
            return resp.get("result", resp)
        return {"status": "error", "error": f"unsupported tool {name}"}

    def _append_transcript(self, session: str, item: dict) -> None:
        p = self.transcripts / f"{session.replace(':', '_')}.jsonl"
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    def ops(self):
        return {"gateway.handle_user_message": self.handle_user_message}
