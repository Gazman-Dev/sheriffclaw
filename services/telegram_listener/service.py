from __future__ import annotations

import asyncio
import json
import os

import requests

from shared.oplog import get_op_logger
from shared.paths import gw_root
from shared.proc_rpc import ProcClient


class TelegramListenerService:
    def __init__(self):
        self.log = get_op_logger("telegram-listener")
        self.log.info("telegram-listener boot (build=delta-fallback-v2)")
        self.gateway = ProcClient("sheriff-gateway")
        self.sheriff_gate = ProcClient("sheriff-tg-gate")
        self.cli_gate = ProcClient("sheriff-cli-gate")
        self.offset_path = gw_root() / "state" / "telegram_offsets.json"
        self.tokens_cache_path = gw_root() / "state" / "telegram_tokens_cache.json"
        self.unlock_channel_path = gw_root() / "state" / "telegram_unlock_channel.json"
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)
        self._webhook_cleared: set[str] = set()
        self._llm_missing_notified = False
        self.debug_mode = os.environ.get("SHERIFF_DEBUG", "").strip().lower() in {"1", "true", "yes"}

    def _append_debug_outbox(self, item: dict) -> None:
        p = gw_root() / "state" / "debug" / "telegram_outbox.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def _http_post(self, url: str, *, payload: dict, timeout: int):
        if self.debug_mode:
            self._append_debug_outbox({"method": "POST", "url": url, "json": payload})

            class _Resp:
                status_code = 200
                text = '{"ok":true}'

                def json(self):
                    return {"ok": True, "result": []}

            return _Resp()
        return requests.post(url, json=payload, timeout=timeout)

    def _http_get(self, url: str, *, params: dict, timeout: int):
        if self.debug_mode:
            self._append_debug_outbox({"method": "GET", "url": url, "params": params})

            class _Resp:
                status_code = 200
                text = '{"ok":true,"result":[]}'

                def json(self):
                    return {"ok": True, "result": []}

            return _Resp()
        return requests.get(url, params=params, timeout=timeout)

    async def _secrets(self, op: str, payload: dict):
        _, res = await self.gateway.request("gateway.secrets.call", {"op": op, "payload": payload})
        outer = res.get("result", {})
        if isinstance(outer, dict) and "result" in outer:
            if not outer.get("ok", True):
                return {}
            inner = outer.get("result", {})
            return inner if isinstance(inner, dict) else {}
        return outer if isinstance(outer, dict) else {}

    def _load_offsets(self) -> dict:
        if not self.offset_path.exists():
            return {"llm": 0, "sheriff": 0}
        try:
            return json.loads(self.offset_path.read_text(encoding="utf-8"))
        except Exception:
            return {"llm": 0, "sheriff": 0}

    def _save_offsets(self, offsets: dict) -> None:
        self.offset_path.write_text(json.dumps(offsets, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_tokens_cache(self) -> dict:
        if not self.tokens_cache_path.exists():
            return {"llm": "", "sheriff": ""}
        try:
            obj = json.loads(self.tokens_cache_path.read_text(encoding="utf-8"))
            return {"llm": str(obj.get("llm", "")), "sheriff": str(obj.get("sheriff", ""))}
        except Exception:
            return {"llm": "", "sheriff": ""}

    def _save_tokens_cache(self, tokens: dict) -> None:
        self.tokens_cache_path.write_text(json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_unlock_channel(self) -> dict:
        if not self.unlock_channel_path.exists():
            return {"token": "", "user_id": ""}
        try:
            obj = json.loads(self.unlock_channel_path.read_text(encoding="utf-8"))
            return {"token": str(obj.get("token", "")), "user_id": str(obj.get("user_id", ""))}
        except Exception:
            return {"token": "", "user_id": ""}

    def _load_unlock_channel_token(self) -> str:
        return self._load_unlock_channel().get("token", "")

    def _send_message(self, token: str, chat_id: int | str, text: str) -> None:
        try:
            r = self._http_post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                payload={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                timeout=20,
            )
            self.log.info("sendMessage chat_id=%s status=%s body=%s", chat_id, r.status_code, (r.text or "")[:240])
        except Exception as e:
            self.log.exception("sendMessage failed chat_id=%s err=%s", chat_id, e)

    def _ensure_long_polling(self, token: str) -> None:
        if not token or token in self._webhook_cleared:
            return
        try:
            r = self._http_post(
                f"https://api.telegram.org/bot{token}/deleteWebhook",
                payload={"drop_pending_updates": False},
                timeout=15,
            )
            self.log.info("deleteWebhook status=%s body=%s", r.status_code, (r.text or "")[:240])
        except Exception as e:
            self.log.exception("deleteWebhook failed: %s", e)
            return
        self._webhook_cleared.add(token)

    async def _handle_ai_message(self, token: str, sheriff_token: str, user_id: str, chat_id: int, text: str):
        unlocked = await self._secrets("secrets.is_unlocked", {})
        if not unlocked.get("unlocked"):
            msg = "🔒 Vault is locked. Send /unlock <master_password> in Sheriff bot, then retry."
            self._send_message(token, chat_id, msg)
            if sheriff_token:
                self._send_message(sheriff_token, chat_id, msg)
            self.log.info("ai blocked while locked user_id=%s", user_id)
            return

        role = "llm"
        st = await self._secrets("secrets.activation.status", {"bot_role": role})
        bound = st.get("user_id")
        if not bound or str(bound) != user_id:
            if text.startswith("activate "):
                code = text.split(" ", 1)[1].strip().lower()
                claim = await self._secrets("secrets.activation.claim", {"bot_role": role, "code": code})
                if claim.get("ok"):
                    self._send_message(token, chat_id, "✅ Activated. You can chat now.")
                    return
            c = await self._secrets("secrets.activation.create", {"bot_role": role, "user_id": user_id})
            code = c.get("code", "")
            if code:
                self._send_message(token, chat_id, f"Your activation code is: {code}")
            return

        self.log.info("ai inbound status=accepted user_id=%s", user_id)

        stream, final = await self.gateway.request(
            "gateway.handle_user_message",
            {"channel": "telegram", "principal_external_id": user_id, "text": text},
            stream_events=True,
        )
        reply = None
        delta_parts: list[str] = []
        async for frame in stream:
            ev = frame.get("event")
            if ev == "assistant.final":
                reply = frame.get("payload", {}).get("text")
            elif ev == "assistant.delta":
                part = str((frame.get("payload") or {}).get("text") or "")
                if part:
                    delta_parts.append(part)
        final_res = await final if asyncio.isfuture(final) or asyncio.iscoroutine(final) else final

        if not reply and delta_parts:
            reply = "".join(delta_parts).strip()

        if reply:
            self._send_message(token, chat_id, reply)

        result_obj = (final_res or {}).get("result", {}) if isinstance(final_res, dict) else {}
        status_obj = result_obj.get("status")
        self.log.info("ai gateway final status=%s has_reply=%s delta_parts=%s", status_obj, bool(reply),
                      len(delta_parts))
        if status_obj == "locked":
            # Always notify on Sheriff channel too, so user can unlock right there.
            msg = "🔒 Vault is locked. Open the Sheriff bot and send: /unlock <master_password>"
            if sheriff_token:
                self._send_message(sheriff_token, chat_id, msg)
            elif not reply:
                self._send_message(token, chat_id, msg)
        elif not reply:
            self._send_message(token, chat_id, "⚠️ No response generated. Please try again in a moment.")

    async def _handle_sheriff_message(self, token: str, user_id: str, chat_id: int, text: str):
        # Direct unlock path for reliability during locked-state recovery.
        if text.startswith("/unlock"):
            parts = text.split(" ", 1)
            if len(parts) < 2 or not parts[1].strip():
                self._send_message(token, chat_id, "Usage: /unlock <master_password>")
                return
            mp = parts[1].strip()
            r = await self._secrets("secrets.unlock", {"master_password": mp})
            self.log.info("unlock attempt user_id=%s ok=%s", user_id, bool(r.get("ok")))
            if r.get("ok"):
                self._send_message(token, chat_id, "✅ Vault unlocked.")
            else:
                self._send_message(token, chat_id, "❌ Unlock failed.")
            return

        _, gate = await self.sheriff_gate.request("gate.inbound_message", {"user_id": user_id, "text": text})
        result = gate.get("result", {})
        status = result.get("status")
        self.log.info("sheriff inbound status=%s user_id=%s", status, user_id)
        if status == "activation_required":
            code = result.get("activation_code", "")
            self._send_message(token, chat_id, f"Your activation code is: {code}")
            return
        if status == "activated":
            self._send_message(token, chat_id, "✅ Sheriff activated.")
            return
        if status != "accepted":
            return

        if text.startswith("/"):
            _, out = await self.cli_gate.request("cli.handle_message", {"text": text})
            msg = out.get("result", {}).get("message", "ok")
            self._send_message(token, chat_id, msg)
            return

        # Non-command messages on Sheriff channel should still guide user.
        self._send_message(token, chat_id, "Sheriff channel commands: /unlock <master_password>, /status")

    async def _poll_bot(self, role: str, token: str, sheriff_token: str, offsets: dict):
        self._ensure_long_polling(token)
        offset = int(offsets.get(role, 0))
        try:
            r = self._http_get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"timeout": 25, "allowed_updates": '["message"]', "offset": offset},
                timeout=35,
            )
            data = r.json()
            updates = data.get("result", []) if isinstance(data, dict) else []
            self.log.info("poll role=%s status=%s count=%s offset=%s", role, r.status_code, len(updates), offset)
        except Exception as e:
            self.log.exception("poll failed role=%s err=%s", role, e)
            return

        for upd in updates:
            uid = int(upd.get("update_id", 0))
            offset = max(offset, uid + 1)
            msg = upd.get("message") or {}
            user_id = str((msg.get("from") or {}).get("id") or "")
            chat_id = (msg.get("chat") or {}).get("id")
            text = (msg.get("text") or "").strip()
            if not user_id or chat_id is None or not text:
                continue
            if role == "llm":
                self.log.info("dispatch role=llm user_id=%s text=%s", user_id, text[:80])
                await self._handle_ai_message(token, sheriff_token, user_id, int(chat_id), text)
            else:
                self.log.info("dispatch role=sheriff user_id=%s text=%s", user_id, text[:80])
                await self._handle_sheriff_message(token, user_id, int(chat_id), text)

        offsets[role] = offset

    async def run_forever(self):
        offsets = self._load_offsets()
        cached_tokens = self._load_tokens_cache()
        while True:
            try:
                llm_live = (await self._secrets("secrets.get_llm_bot_token", {})).get("token", "")
                sheriff_live = (await self._secrets("secrets.get_gate_bot_token", {})).get("token", "")

                llm_token = llm_live or cached_tokens.get("llm", "")
                sheriff_token = sheriff_live or cached_tokens.get("sheriff", "")
                # Security policy: when Telegram unlock is enabled, sheriff token may be mirrored
                # outside vault for unlock continuity; use it as last resort for sheriff channel only.
                if not sheriff_token:
                    sheriff_token = self._load_unlock_channel_token()
                    if sheriff_token:
                        self.log.info("using unlock-channel sheriff token fallback")

                # Refresh cache only when we have live values.
                changed = False
                if llm_live and llm_live != cached_tokens.get("llm", ""):
                    cached_tokens["llm"] = llm_live
                    changed = True
                if sheriff_live and sheriff_live != cached_tokens.get("sheriff", ""):
                    cached_tokens["sheriff"] = sheriff_live
                    changed = True
                if changed:
                    self._save_tokens_cache(cached_tokens)

                specs = [("llm", llm_token), ("sheriff", sheriff_token)]
                if not llm_token:
                    self.log.info("llm token unavailable (vault likely locked); waiting for sheriff unlock")
                    if sheriff_token and not self._llm_missing_notified:
                        unlock_ch = self._load_unlock_channel()
                        uid = unlock_ch.get("user_id", "")
                        if uid:
                            self._send_message(
                                sheriff_token,
                                int(uid),
                                "ℹ️ LLM bot token unavailable while vault is locked. Send /unlock <master_password> in Sheriff bot, then retry AI bot.",
                            )
                        self._llm_missing_notified = True
                else:
                    self._llm_missing_notified = False
                for role, token in specs:
                    if token:
                        await self._poll_bot(role, token, sheriff_token, offsets)
                self._save_offsets(offsets)
            except Exception:
                await asyncio.sleep(2)
                continue
            await asyncio.sleep(0.2)
