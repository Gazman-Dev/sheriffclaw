from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone

from shared.identity import principal_id_for_channel
from shared.llm.device_auth import refresh_access_token
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

    def _debug_mode_enabled(self) -> bool:
        p = gw_root() / "state" / "debug_mode.json"
        if not p.exists():
            return False
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            return bool(obj.get("enabled", False))
        except Exception:
            return False

    def _pop_debug_message(self) -> dict:
        p = gw_root() / "state" / "debug.agent.jsonl"
        if not p.exists():
            raise RuntimeError("debug.agent.jsonl missing")
        lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not lines:
            raise RuntimeError("debug.agent.jsonl is empty")
        first = lines[0]
        p.write_text(("\n".join(lines[1:]) + ("\n" if len(lines) > 1 else "")), encoding="utf-8")
        return json.loads(first)

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

        provider_name = "stub"
        api_key = ""
        base_url = ""
        try:
            _, prov = await self.secrets.request("secrets.get_llm_provider", {})
            provider_name = prov.get("result", {}).get("provider") or provider_name
            if provider_name == "openai-codex-chatgpt":
                _, auth = await self.secrets.request("secrets.get_llm_auth", {})
                auth_obj = auth.get("result", {}).get("auth") or {}
                api_key = auth_obj.get("access_token") or ""
                expires_at = auth_obj.get("expires_at")
                refresh = auth_obj.get("refresh_token")
                if expires_at and refresh:
                    try:
                        exp_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")).astimezone(timezone.utc)
                        if exp_dt <= datetime.now(timezone.utc):
                            tok = refresh_access_token(refresh)
                            auth_obj.update(
                                {
                                    "access_token": tok.access_token,
                                    "refresh_token": tok.refresh_token,
                                    "id_token": tok.id_token,
                                    "obtained_at": tok.obtained_at,
                                    "expires_at": tok.expires_at,
                                }
                            )
                            await self.secrets.request("secrets.set_llm_auth", {"auth": auth_obj})
                            api_key = auth_obj.get("access_token") or ""
                    except Exception:
                        pass
            else:
                _, key = await self.secrets.request("secrets.get_llm_api_key", {})
                api_key = key.get("result", {}).get("api_key") or ""
        except Exception:
            pass

        if self._debug_mode_enabled():
            msg = self._pop_debug_message()
            out_text = msg.get("text") or msg.get("content") or json.dumps(msg, ensure_ascii=False)
            await emit_event("assistant.final", {"text": out_text})
            append_jsonl(gw_root() / "state" / "transcripts" / f"{session.replace(':','_')}.jsonl", {"role": "assistant", "content": out_text})
            return {"status": "debug", "session_handle": session}

        stream, final = await self.ai.request(
            "agent.session.user_message",
            {
                "session_handle": session,
                "text": text,
                "model_ref": payload.get("model_ref"),
                "provider_name": provider_name,
                "api_key": api_key,
                "base_url": base_url,
            },
            stream_events=True,
        )
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
        if inspect.isawaitable(final):
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
            if not res.get("ok", True):
                return {"status": "needs_secret", "handle": payload.get("handle"), "error": res.get("error", "secrets_unavailable")}
            if res.get("result", {}).get("ok"):
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
