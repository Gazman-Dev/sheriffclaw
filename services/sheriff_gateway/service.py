from __future__ import annotations

import inspect
import json
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

from shared.identity import principal_id_for_channel
from shared.llm.device_auth import refresh_access_token
from shared.oplog import get_op_logger
from shared.paths import gw_root
from shared.proc_rpc import ProcClient
from shared.transcript import append_jsonl


class SheriffGatewayService:
    ALLOWED_SECRETS_OPS = {
        "secrets.verify_master_password",
        "secrets.unlock",
        "secrets.is_unlocked",
        "secrets.initialize",
        "secrets.get_llm_provider",
        "secrets.set_llm_provider",
        "secrets.get_llm_api_key",
        "secrets.set_llm_api_key",
        "secrets.get_llm_auth",
        "secrets.set_llm_auth",
        "secrets.clear_llm_auth",
        "secrets.get_llm_bot_token",
        "secrets.set_llm_bot_token",
        "secrets.get_gate_bot_token",
        "secrets.set_gate_bot_token",
        "secrets.get_secret",
        "secrets.set_secret",
        "secrets.ensure_handle",
        "secrets.activation.create",
        "secrets.activation.claim",
        "secrets.activation.status",
        "secrets.telegram_webhook.get",
        "secrets.telegram_webhook.set",
    }

    def __init__(self) -> None:
        self.ai = ProcClient("ai-worker")
        self.web = ProcClient("sheriff-web")
        self.tools = ProcClient("sheriff-tools")
        self.secrets = ProcClient("sheriff-secrets")
        self.requests = ProcClient("sheriff-requests")
        self.tg_gate = ProcClient("sheriff-tg-gate")
        self.log = get_op_logger("gateway")
        self.sessions: dict[str, str] = {}
        self._queue = defaultdict(deque)
        self._processing = set()
        self._queue_cond = None
        self._queue_paused = False
        self._queue_pause_reason = ""

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

    async def _ensure_queue_cond(self):
        import asyncio

        if self._queue_cond is None:
            self._queue_cond = asyncio.Condition()
        return self._queue_cond

    async def _process_message(self, principal_id: str, payload, emit_event):
        text = payload.get("text", "")
        session = self.sessions.get(principal_id)
        if not session:
            _, opened = await self.ai.request("agent.session.open", {"session_id": principal_id})
            session = opened["result"]["session_handle"]
            self.sessions[principal_id] = session

        append_jsonl(gw_root() / "state" / "transcripts" / f"{session.replace(':','_')}.jsonl", {"role": "user", "content": text})

        debug_mode = self._debug_mode_enabled()
        provider_name = "stub"
        api_key = ""
        base_url = ""

        _, unlocked = await self.secrets.request("secrets.is_unlocked", {})
        vault_known_locked = unlocked.get("ok") is True and unlocked.get("result", {}).get("unlocked") is False
        if vault_known_locked:
            supplied_mp = (payload.get("master_password") or "").strip()
            if supplied_mp:
                _, u = await self.secrets.request("secrets.unlock", {"master_password": supplied_mp})
                if u.get("result", {}).get("ok"):
                    _, unlocked = await self.secrets.request("secrets.is_unlocked", {})
                    vault_known_locked = unlocked.get("ok") is True and unlocked.get("result", {}).get("unlocked") is False
            if vault_known_locked:
                msg = "🔒 Sheriff vault is locked. Run /unlock <master_password> first."
                await emit_event("assistant.final", {"text": msg})
                append_jsonl(gw_root() / "state" / "transcripts" / f"{session.replace(':','_')}.jsonl", {"role": "assistant", "content": msg})
                return {"status": "locked", "session_handle": session}

        if unlocked.get("ok") is True and unlocked.get("result", {}).get("unlocked"):
            _, prov = await self.secrets.request("secrets.get_llm_provider", {})
            if not prov.get("ok"):
                if not debug_mode:
                    msg = "Sheriff could not read LLM provider from vault."
                    await emit_event("assistant.final", {"text": msg})
                    append_jsonl(gw_root() / "state" / "transcripts" / f"{session.replace(':','_')}.jsonl", {"role": "assistant", "content": msg})
                    return {"status": "provider_error", "session_handle": session}
            else:
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
                                auth_obj.update({"access_token": tok.access_token, "refresh_token": tok.refresh_token, "id_token": tok.id_token, "obtained_at": tok.obtained_at, "expires_at": tok.expires_at})
                                await self.secrets.request("secrets.set_llm_auth", {"auth": auth_obj})
                                api_key = auth_obj.get("access_token") or ""
                        except Exception:
                            pass
                    if not api_key and not debug_mode:
                        msg = "LLM auth missing/expired. Re-run onboarding login or configure-llm."
                        await emit_event("assistant.final", {"text": msg})
                        append_jsonl(gw_root() / "state" / "transcripts" / f"{session.replace(':','_')}.jsonl", {"role": "assistant", "content": msg})
                        return {"status": "llm_auth_missing", "session_handle": session}
                elif provider_name == "openai-codex":
                    _, key = await self.secrets.request("secrets.get_llm_api_key", {})
                    api_key = key.get("result", {}).get("api_key") or ""
                    if not api_key and not debug_mode:
                        msg = "OpenAI API key missing. Run: sheriff-ctl configure-llm --provider openai-codex"
                        await emit_event("assistant.final", {"text": msg})
                        append_jsonl(gw_root() / "state" / "transcripts" / f"{session.replace(':','_')}.jsonl", {"role": "assistant", "content": msg})
                        return {"status": "llm_key_missing", "session_handle": session}

        if self._debug_mode_enabled():
            msg = self._pop_debug_message()
            out_text = msg.get("text") or msg.get("content") or json.dumps(msg, ensure_ascii=False)
            await emit_event("assistant.final", {"text": out_text})
            append_jsonl(gw_root() / "state" / "transcripts" / f"{session.replace(':','_')}.jsonl", {"role": "assistant", "content": out_text})
            return {"status": "debug", "session_handle": session}

        stream, final = await self.ai.request("agent.session.user_message", {"session_handle": session, "text": text, "model_ref": payload.get("model_ref"), "provider_name": provider_name, "api_key": api_key, "base_url": base_url}, stream_events=True)
        saw_final = False
        delta_parts: list[str] = []
        event_counts: dict[str, int] = {}
        async for frame in stream:
            ev = frame.get("event")
            event_counts[ev] = event_counts.get(ev, 0) + 1
            if ev == "tool.call":
                result = await self._route_tool(principal_id, frame.get("payload", {}))
                await emit_event("tool.result", result)
                await self.ai.request("agent.session.tool_result", {"session_handle": session, "tool_name": frame["payload"].get("tool_name", "tool"), "result": result})
                continue
            if ev == "assistant.final":
                saw_final = True
            elif ev == "assistant.delta":
                part = str((frame.get("payload") or {}).get("text") or "")
                if part:
                    delta_parts.append(part)
            await emit_event(ev, frame.get("payload", {}))

        final_res = await final if inspect.isawaitable(final) else final
        self.log.info(
            "ai_stream session=%s events=%s saw_final=%s deltas=%s final_ok=%s final_err=%s",
            session,
            event_counts,
            saw_final,
            len(delta_parts),
            (final_res or {}).get("ok") if isinstance(final_res, dict) else None,
            (final_res or {}).get("error") if isinstance(final_res, dict) else None,
        )
        if isinstance(final_res, dict) and final_res.get("ok") is False:
            err = final_res.get("error") or "unknown_error"
            msg = f"AI worker error: {err}"
            await emit_event("assistant.final", {"text": msg})
            append_jsonl(gw_root() / "state" / "transcripts" / f"{session.replace(':','_')}.jsonl", {"role": "assistant", "content": msg})
            return {"status": "ai_error", "session_handle": session}

        if not saw_final:
            if delta_parts:
                msg = "".join(delta_parts).strip() or "AI produced partial output only."
            else:
                msg = "AI produced no final response."
            await emit_event("assistant.final", {"text": msg})
            append_jsonl(gw_root() / "state" / "transcripts" / f"{session.replace(':','_')}.jsonl", {"role": "assistant", "content": msg})

        return {"status": "done", "session_handle": session}

    async def handle_user_message(self, payload, emit_event, req_id):
        channel = payload.get("channel", "cli")
        principal_id = principal_id_for_channel(channel, payload["principal_external_id"])
        queue_id = str(uuid.uuid4())
        append_jsonl(gw_root() / "state" / "message_queue.jsonl", {"event": "enqueue", "principal_id": principal_id, "queue_id": queue_id, "text": payload.get("text", "")})

        cond = await self._ensure_queue_cond()
        async with cond:
            self._queue[principal_id].append(queue_id)
            while True:
                is_head = self._queue[principal_id] and self._queue[principal_id][0] == queue_id
                busy = principal_id in self._processing
                if is_head and not busy and not self._queue_paused:
                    self._processing.add(principal_id)
                    break
                await cond.wait()

        try:
            out = await self._process_message(principal_id, payload, emit_event)
            append_jsonl(gw_root() / "state" / "message_queue.jsonl", {"event": "dequeue", "principal_id": principal_id, "queue_id": queue_id})
            return out
        finally:
            async with cond:
                if self._queue[principal_id] and self._queue[principal_id][0] == queue_id:
                    self._queue[principal_id].popleft()
                self._processing.discard(principal_id)
                cond.notify_all()

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

    async def queue_control(self, payload, emit_event, req_id):
        cond = await self._ensure_queue_cond()
        pause = bool(payload.get("pause", False))
        reason = payload.get("reason", "")
        async with cond:
            self._queue_paused = pause
            self._queue_pause_reason = reason if pause else ""
            cond.notify_all()
        return {"ok": True, "paused": self._queue_paused, "reason": self._queue_pause_reason}

    async def queue_status(self, payload, emit_event, req_id):
        pending = sum(len(v) for v in self._queue.values())
        return {"paused": self._queue_paused, "pause_reason": self._queue_pause_reason, "processing": len(self._processing), "pending": pending}

    async def verify_master_password(self, payload, emit_event, req_id):
        master_password = payload.get("master_password") or ""
        _, res = await self.secrets.request("secrets.verify_master_password", {"master_password": master_password})
        return {"ok": bool(res.get("result", {}).get("ok"))}

    async def secrets_call(self, payload, emit_event, req_id):
        op = str(payload.get("op") or "")
        if op not in self.ALLOWED_SECRETS_OPS:
            return {"ok": False, "error": "op_not_allowed", "op": op}
        req_payload = payload.get("payload") or {}
        _, res = await self.secrets.request(op, req_payload)
        return {"ok": bool(res.get("ok", True)), "result": res.get("result", {}), "error": res.get("error")}

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
            "gateway.queue.control": self.queue_control,
            "gateway.queue.status": self.queue_status,
            "gateway.verify_master_password": self.verify_master_password,
            "gateway.secrets.call": self.secrets_call,
        }
