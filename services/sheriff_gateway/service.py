from __future__ import annotations

import inspect
import json
import os
import uuid
from collections import defaultdict, deque
from shared.codex_auth import codex_auth_help_text, is_codex_auth_error
from shared.codex_output import extract_text_content
from shared.identity import principal_id_for_channel
from shared.oplog import get_op_logger
from shared.paths import gw_root
from shared.proc_rpc import ProcClient
from shared.session_keys import session_key_for_message
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
        self.ai = ProcClient("codex-mcp-host", spawn_fallback=False)
        self.web = ProcClient("sheriff-web", spawn_fallback=False)
        self.tools = ProcClient("sheriff-tools", spawn_fallback=False)
        self.secrets = ProcClient("sheriff-secrets", spawn_fallback=False)
        self.requests = ProcClient("sheriff-requests", spawn_fallback=False)
        self.tg_gate = ProcClient("sheriff-tg-gate", spawn_fallback=False)
        self.log = get_op_logger("gateway")
        self.sessions: set[str] = set()
        self._queue = defaultdict(deque)
        self._processing = set()
        self._queue_cond = None
        self._queue_paused = False
        self._queue_pause_reason = ""

    async def _ensure_queue_cond(self):
        import asyncio

        if self._queue_cond is None:
            self._queue_cond = asyncio.Condition()
        return self._queue_cond

    async def _process_message(self, principal_id: str, payload, emit_event):
        text = payload.get("text", "")

        session = self._session_key(payload)
        if session not in self.sessions:
            await self.ai.request("codex.session.ensure", {"session_key": session, "hydrate": False})
            self.sessions.add(session)

        await self.ai.request(
            "codex.memory.inbox.append",
            {
                "session_key": session,
                "text": text,
                "channel": payload.get("channel", "cli"),
                "principal_id": principal_id,
                "metadata": {
                    "chat_id": payload.get("chat_id"),
                    "chat_type": payload.get("chat_type"),
                    "message_thread_id": payload.get("message_thread_id"),
                },
            },
        )

        append_jsonl(gw_root() / "state" / "transcripts" / f"{session}.jsonl", {"role": "user", "content": text})

        debug_mode = os.environ.get("SHERIFF_DEBUG", "").strip().lower() in {"1", "true", "yes"}
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
                    vault_known_locked = unlocked.get("ok") is True and unlocked.get("result", {}).get(
                        "unlocked") is False
            if vault_known_locked:
                msg = "🔒 Sheriff vault is locked. Run /unlock <master_password> first."
                await emit_event("assistant.final", {"text": msg})
                append_jsonl(gw_root() / "state" / "transcripts" / f"{session}.jsonl",
                             {"role": "assistant", "content": msg})
                return {"status": "locked", "session_handle": session}

        if unlocked.get("ok") is True and unlocked.get("result", {}).get("unlocked"):
            _, prov = await self.secrets.request("secrets.get_llm_provider", {})
            if not prov.get("ok"):
                if not debug_mode:
                    msg = "Sheriff could not read LLM provider from vault."
                    await emit_event("assistant.final", {"text": msg})
                    append_jsonl(gw_root() / "state" / "transcripts" / f"{session}.jsonl",
                                 {"role": "assistant", "content": msg})
                    return {"status": "provider_error", "session_handle": session}
            else:
                provider_name = prov.get("result", {}).get("provider") or provider_name
                if provider_name == "openai-codex-chatgpt":
                    # Codex subscription login is managed by the local Codex repo state.
                    api_key = ""
                    if not payload.get("model_ref"):
                        payload["model_ref"] = "gpt-5-codex"
                elif provider_name == "openai-codex":
                    _, key = await self.secrets.request("secrets.get_llm_api_key", {})
                    api_key = key.get("result", {}).get("api_key") or ""
                    if not api_key and not debug_mode:
                        msg = "OpenAI API key missing. Run: sheriff configure-llm --provider openai-codex"
                        await emit_event("assistant.final", {"text": msg})
                        append_jsonl(gw_root() / "state" / "transcripts" / f"{session}.jsonl",
                                     {"role": "assistant", "content": msg})
                        return {"status": "llm_key_missing", "session_handle": session}
        stream, final = await self.ai.request(
            "codex.session.send",
            {
                "session_key": session,
                "prompt": text,
                "model_ref": payload.get("model_ref"),
                "provider_name": provider_name,
                "api_key": api_key,
                "base_url": base_url,
                "channel": payload.get("channel", "cli"),
                "principal_external_id": payload.get("principal_external_id", "unknown"),
            },
            stream_events=True,
        )
        saw_final = False
        delta_parts: list[str] =[]
        event_counts: dict[str, int] = {}
        async for frame in stream:
            ev = frame.get("event")
            event_counts[ev] = event_counts.get(ev, 0) + 1
            if ev == "tool.call":
                result = await self._route_tool(principal_id, frame.get("payload", {}))
                await emit_event("tool.result", result)
                continue
            if ev == "assistant.final":
                saw_final = True
            elif ev == "assistant.delta":
                part = str((frame.get("payload") or {}).get("text") or "")
                if part:
                    delta_parts.append(part)
            await emit_event(ev, frame.get("payload", {}))

        final_res = await final if inspect.isawaitable(final) else final
        if isinstance(final_res, dict) and isinstance(final_res.get("result"), dict):
            final_payload = final_res.get("result", {})
        elif isinstance(final_res, dict):
            final_payload = final_res
        else:
            final_payload = {}
        final_tool_result = final_payload.get("result", {}) if isinstance(final_payload, dict) else {}
        self.log.info(
            "ai_stream session=%s events=%s saw_final=%s deltas=%s final_ok=%s final_err=%s",
            session,
            event_counts,
            saw_final,
            len(delta_parts),
            final_payload.get("ok") if isinstance(final_payload, dict) else None,
            final_payload.get("error") if isinstance(final_payload, dict) else None,
        )
        if isinstance(final_payload, dict) and final_payload.get("ok") is False:
            err = final_payload.get("error") or "unknown_error"
            self.log.warning(
                "ai_stream_error session=%s provider=%s model=%s payload=%s",
                session,
                provider_name,
                payload.get("model_ref"),
                json.dumps(final_payload, ensure_ascii=False, default=str)[:4000],
            )
            if provider_name == "openai-codex-chatgpt" and is_codex_auth_error(str(err)):
                msg = codex_auth_help_text(interactive_login_supported=payload.get("channel", "cli") == "cli")
                status = "auth_required"
            else:
                msg = f"AI worker error: {err}"
                status = "ai_error"
            await emit_event("assistant.final", {"text": msg})
            append_jsonl(gw_root() / "state" / "transcripts" / f"{session}.jsonl",
                         {"role": "assistant", "content": msg})
            return {"status": status, "session_handle": session}

        if not saw_final:
            final_text = extract_text_content(final_tool_result) if isinstance(final_tool_result, dict) else ""
            self.log.warning(
                "ai_stream_missing_final session=%s provider=%s model=%s deltas=%s final_payload=%s final_tool_result=%s",
                session,
                provider_name,
                payload.get("model_ref"),
                len(delta_parts),
                json.dumps(final_payload, ensure_ascii=False, default=str)[:4000],
                json.dumps(final_tool_result, ensure_ascii=False, default=str)[:4000],
            )
            if final_text:
                msg = final_text
            elif delta_parts:
                msg = "".join(delta_parts).strip() or "AI produced partial output only."
            else:
                msg = "AI produced no final response."
            await emit_event("assistant.final", {"text": msg})
            append_jsonl(gw_root() / "state" / "transcripts" / f"{session}.jsonl",
                         {"role": "assistant", "content": msg})

        return {"status": "done", "session_handle": session}

    def _session_key(self, payload: dict) -> str:
        return session_key_for_message(str(payload.get("channel", "cli")), payload)

    async def handle_user_message(self, payload, emit_event, req_id):
        channel = payload.get("channel", "cli")
        principal_id = principal_id_for_channel(channel, payload["principal_external_id"])
        queue_id = str(uuid.uuid4())
        append_jsonl(gw_root() / "state" / "message_queue.jsonl",
                     {"event": "enqueue", "principal_id": principal_id, "queue_id": queue_id,
                      "text": payload.get("text", "")})

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
            append_jsonl(gw_root() / "state" / "message_queue.jsonl",
                         {"event": "dequeue", "principal_id": principal_id, "queue_id": queue_id})
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
                return {"status": "needs_secret", "handle": payload.get("handle"),
                        "error": res.get("error", "secrets_unavailable")}
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
        return {"paused": self._queue_paused, "pause_reason": self._queue_pause_reason,
                "processing": len(self._processing), "pending": pending}

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

    async def _send_llm_telegram(self, text: str):
        _, res = await self.secrets.request("secrets.get_llm_bot_token", {})
        token = res.get("result", {}).get("token", "")
        if not token:
            return

        _, st = await self.secrets.request("secrets.activation.status", {"bot_role": "llm"})
        user_id = st.get("result", {}).get("user_id")
        if not user_id:
            return

        import requests
        import asyncio

        def _post_chunk(chunk):
            try:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": int(str(user_id).strip()), "text": chunk, "disable_web_page_preview": True},
                    timeout=10
                )
            except Exception:
                pass

        MAX_LEN = 4000
        for i in range(0, len(text), MAX_LEN):
            chunk = text[i:i+MAX_LEN]
            await asyncio.to_thread(_post_chunk, chunk)

    async def notify_request_resolved(self, payload, emit_event, req_id):
        if not self.sessions:
            return {"status": "no_session"}
        session_handle = next(iter(self.sessions))
        result = {"type": payload.get("type"), "key": payload.get("key"), "status": payload.get("status")}
        append_jsonl(
            gw_root() / "state" / "transcripts" / f"{session_handle}.jsonl",
            {"role": "tool", "name": "requests.resolved", "content": result},
            )

        async def _emit(ev, p):
            if ev == "assistant.final":
                text = p.get("text")
                if text:
                    await self._send_llm_telegram(text)

        _, st = await self.secrets.request("secrets.activation.status", {"bot_role": "llm"})
        user_id = st.get("result", {}).get("user_id") or "system"

        trigger_msg = (
            "A Sheriff request resolution event occurred.\n"
            "Review the repository tasks and memory, update them if warranted, and then respond appropriately.\n\n"
            "## Request Resolution Event\n"
            f"- type: {payload.get('type')}\n"
            f"- key: {payload.get('key')}\n"
            f"- status: {payload.get('status')}\n"
        )

        import asyncio
        asyncio.create_task(
            self.handle_user_message(
                {"channel": "telegram", "principal_external_id": user_id, "text": trigger_msg},
                _emit,
                f"sys-trigger-{uuid.uuid4()}"
            )
        )

        return {"status": "notified", "session_handle": session_handle}

    async def reset_session(self, payload, emit_event, req_id):
        session = str(payload.get("session_id") or self._session_key(payload))
        if session in self.sessions:
            self.sessions.discard(session)
            await self.ai.request("codex.session.invalidate", {"session_key": session, "reason": "reset"})
        return {"status": "reset", "session_handle": session}

    def ops(self):
        return {
            "gateway.handle_user_message": self.handle_user_message,
            "gateway.notify_request_resolved": self.notify_request_resolved,
            "gateway.session.reset": self.reset_session,
            "gateway.queue.control": self.queue_control,
            "gateway.queue.status": self.queue_status,
            "gateway.verify_master_password": self.verify_master_password,
            "gateway.secrets.call": self.secrets_call,
        }
