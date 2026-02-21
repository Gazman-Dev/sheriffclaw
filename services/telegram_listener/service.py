from __future__ import annotations

import asyncio
import json
from pathlib import Path

import requests

from shared.paths import gw_root
from shared.proc_rpc import ProcClient


class TelegramListenerService:
    def __init__(self):
        self.secrets = ProcClient("sheriff-secrets")
        self.gateway = ProcClient("sheriff-gateway")
        self.ai_gate = ProcClient("ai-tg-llm")
        self.sheriff_gate = ProcClient("sheriff-tg-gate")
        self.cli_gate = ProcClient("sheriff-cli-gate")
        self.offset_path = gw_root() / "state" / "telegram_offsets.json"
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_offsets(self) -> dict:
        if not self.offset_path.exists():
            return {"llm": 0, "sheriff": 0}
        try:
            return json.loads(self.offset_path.read_text(encoding="utf-8"))
        except Exception:
            return {"llm": 0, "sheriff": 0}

    def _save_offsets(self, offsets: dict) -> None:
        self.offset_path.write_text(json.dumps(offsets, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _send_message(token: str, chat_id: int | str, text: str) -> None:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                timeout=20,
            )
        except Exception:
            pass

    async def _handle_ai_message(self, token: str, user_id: str, chat_id: int, text: str):
        _, gate = await self.ai_gate.request("ai_tg_llm.inbound_message", {"user_id": user_id, "text": text})
        result = gate.get("result", {})
        status = result.get("status")
        if status == "activation_required":
            code = result.get("activation_code", "")
            self._send_message(token, chat_id, f"Your activation code is: {code}\nReply: activate {code}")
            return
        if status == "activated":
            self._send_message(token, chat_id, "Activated. You can chat now.")
            return
        if status != "accepted":
            return

        stream, final = await self.gateway.request(
            "gateway.handle_user_message",
            {"channel": "telegram", "principal_external_id": user_id, "text": text},
            stream_events=True,
        )
        reply = None
        async for frame in stream:
            if frame.get("event") == "assistant.final":
                reply = frame.get("payload", {}).get("text")
        if asyncio.iscoroutine(final):
            await final
        if reply:
            self._send_message(token, chat_id, reply)

    async def _handle_sheriff_message(self, token: str, user_id: str, chat_id: int, text: str):
        _, gate = await self.sheriff_gate.request("gate.inbound_message", {"user_id": user_id, "text": text})
        result = gate.get("result", {})
        status = result.get("status")
        if status == "activation_required":
            code = result.get("activation_code", "")
            self._send_message(token, chat_id, f"Your activation code is: {code}\nReply: activate {code}")
            return
        if status == "activated":
            self._send_message(token, chat_id, "Sheriff activated.")
            return
        if status != "accepted":
            return

        if text.startswith("/"):
            _, out = await self.cli_gate.request("cli.handle_message", {"text": text})
            msg = out.get("result", {}).get("message", "ok")
            self._send_message(token, chat_id, msg)

    async def _poll_bot(self, role: str, token: str, offsets: dict):
        offset = int(offsets.get(role, 0))
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"timeout": 25, "allowed_updates": '["message"]', "offset": offset},
                timeout=30,
            )
            data = r.json()
            updates = data.get("result", []) if isinstance(data, dict) else []
        except Exception:
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
                await self._handle_ai_message(token, user_id, int(chat_id), text)
            else:
                await self._handle_sheriff_message(token, user_id, int(chat_id), text)

        offsets[role] = offset

    async def run_forever(self):
        offsets = self._load_offsets()
        while True:
            try:
                _, l = await self.secrets.request("secrets.get_llm_bot_token", {})
                _, g = await self.secrets.request("secrets.get_gate_bot_token", {})
                llm_token = l.get("result", {}).get("token", "")
                sheriff_token = g.get("result", {}).get("token", "")

                if llm_token:
                    await self._poll_bot("llm", llm_token, offsets)
                if sheriff_token:
                    await self._poll_bot("sheriff", sheriff_token, offsets)
                self._save_offsets(offsets)
            except Exception:
                await asyncio.sleep(2)
                continue
            await asyncio.sleep(0.2)
