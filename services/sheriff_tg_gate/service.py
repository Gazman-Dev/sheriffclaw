from __future__ import annotations

import json
import os

import requests

from shared.paths import gw_root
from shared.proc_rpc import ProcClient
from shared.transcript import append_jsonl


class SheriffTgGateService:
    def __init__(self):
        self.gateway = ProcClient("sheriff-gateway")
        self.policy = ProcClient("sheriff-policy")
        self.log_path = gw_root() / "state" / "gate_events.jsonl"
        self.debug_mode = os.environ.get("SHERIFF_DEBUG", "").strip().lower() in {"1", "true", "yes"}

    def _send_http(self, url: str, *, payload: dict, timeout: int = 10):
        if self.debug_mode:
            p = gw_root() / "state" / "debug" / "telegram_outbox.jsonl"
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"url": url, "json": payload}, ensure_ascii=False) + "\n")

            class _Resp:
                status_code = 200
                text = '{"ok":true}'

                def json(self):
                    return {"ok": True, "result": {"debug_mock": True}}

            return _Resp()
        return requests.post(url, json=payload, timeout=timeout)

    async def _secrets(self, op: str, payload: dict):
        _, res = await self.gateway.request("gateway.secrets.call", {"op": op, "payload": payload})
        outer = res.get("result", {})
        if isinstance(outer, dict) and "result" in outer:
            if not outer.get("ok", True):
                return {}
            inner = outer.get("result", {})
            return inner if isinstance(inner, dict) else {}
        return outer if isinstance(outer, dict) else {}

    async def _get_bot_token(self) -> str:
        res = await self._secrets("secrets.get_gate_bot_token", {})
        return res.get("token", "")

    async def _send_telegram(self, text: str):
        if self.debug_mode:
            token = "debug-token"
            user_id = "debug-user"
        else:
            token = await self._get_bot_token()
            if not token:
                return

            res = await self._secrets("secrets.activation.status", {"bot_role": "sheriff"})
            user_id = res.get("user_id")
            if not user_id:
                return

        MAX_LEN = 4000
        for i in range(0, len(text), MAX_LEN):
            chunk = text[i:i+MAX_LEN]
            try:
                self._send_http(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    payload={"chat_id": int(str(user_id).strip() or "0"), "text": chunk, "disable_web_page_preview": True},
                    timeout=10,
                )
            except Exception:
                pass

    async def notify_request(self, payload, emit_event, req_id):
        append_jsonl(self.log_path, payload)

        req_type = payload.get("type", "action")
        key = payload.get("key", "unknown")
        one_liner = payload.get("one_liner", "No description provided.")
        context = payload.get("context") or {}
        title = context.get("title", key)

        if req_type == "secret":
            msg = (
                f"🔑 Agent requests {title}, so it can:\n"
                f">> {one_liner}\n\n"
                f"Please reply: /secret {key} <value>\n"
                f"Or to reject: /deny-secret {key}"
            )
        else:
            msg = (
                f"🔔 Sheriff Approval Required\n\n"
                f"The agent asks permission to access {req_type}: {key}\n"
                f"Reason: {one_liner}\n\n"
                f"Reply with /allow-{req_type} {key} or /deny-{req_type} {key}"
            )

        await self._send_telegram(msg)
        return {"status": "sent"}

    async def notify_master_password_required(self, payload, emit_event, req_id):
        await self._send_telegram("🔒 Sheriff vault is locked. Please send: /unlock <password>")
        return {"status": "sent"}

    async def notify_master_password_accepted(self, payload, emit_event, req_id):
        await self._send_telegram("✅ Vault unlocked successfully.")
        return {"status": "sent"}

    async def submit_secret(self, payload, emit_event, req_id):
        return await self._secrets("secrets.set_secret", payload)

    async def inbound_message(self, payload, emit_event, req_id):
        user_id = str(payload.get("user_id", ""))
        text = (payload.get("text") or "").strip()
        role = "sheriff"

        unl = await self._secrets("secrets.is_unlocked", {})
        if not unl.get("unlocked"):
            return {"status": "locked"}

        res = await self._secrets("secrets.activation.status", {"bot_role": role})
        bound = res.get("user_id")

        if bound and str(bound) == user_id:
            return {"status": "accepted", "user_id": user_id}

        if text.startswith("activate "):
            code = text.split(" ", 1)[1].strip().lower()
            claim = await self._secrets("secrets.activation.claim", {"bot_role": role, "code": code})
            if claim.get("ok"):
                return {"status": "activated", "user_id": claim.get("user_id")}

        c = await self._secrets("secrets.activation.create", {"bot_role": role, "user_id": user_id})
        code = c.get("code")
        return {"status": "activation_required", "activation_code": code}

    async def apply_callback(self, payload, emit_event, req_id):
        _, r = await self.policy.request("policy.apply_callback", payload)
        return r["result"]

    def ops(self):
        return {
            "gate.notify_request": self.notify_request,
            "gate.notify_master_password_required": self.notify_master_password_required,
            "gate.notify_master_password_accepted": self.notify_master_password_accepted,
            "gate.submit_secret": self.submit_secret,
            "gate.inbound_message": self.inbound_message,
            "gate.apply_callback": self.apply_callback,
        }