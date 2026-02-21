from __future__ import annotations

import json
import random
import ssl
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

from shared.paths import gw_root
from shared.proc_rpc import ProcClient


class TelegramWebhookService:
    def __init__(self):
        self.secrets = ProcClient("sheriff-secrets")
        self.gateway = ProcClient("sheriff-gateway")
        self.ai_gate = ProcClient("ai-tg-llm")
        self.sheriff_gate = ProcClient("sheriff-tg-gate")
        self.cli_gate = ProcClient("sheriff-cli-gate")
        self.cfg_path = gw_root() / "state" / "telegram_webhook.json"
        self.cfg_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_or_init_cfg(self) -> dict:
        if self.cfg_path.exists():
            return json.loads(self.cfg_path.read_text(encoding="utf-8"))
        cfg = {
            "port": random.randint(20000, 60000),
            "llm_path": f"/telegram/{uuid.uuid4().hex}/llm",
            "sheriff_path": f"/telegram/{uuid.uuid4().hex}/sheriff",
            "llm_secret": uuid.uuid4().hex,
            "sheriff_secret": uuid.uuid4().hex,
        }
        self.cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return cfg

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
        if hasattr(final, "__await__"):
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
            self._send_message(token, chat_id, out.get("result", {}).get("message", "ok"))

    @staticmethod
    def _send_message(token: str, chat_id: int | str, text: str):
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                timeout=20,
            )
        except Exception:
            pass

    async def run_forever(self):
        cfg = self._load_or_init_cfg()
        base_url = (Path(".").resolve(),)
        public_base = __import__("os").environ.get("SHERIFF_WEBHOOK_PUBLIC_BASE", "").strip()
        cert = __import__("os").environ.get("SHERIFF_WEBHOOK_CERT", "").strip()
        key = __import__("os").environ.get("SHERIFF_WEBHOOK_KEY", "").strip()

        if not public_base.startswith("https://"):
            raise RuntimeError("SHERIFF_WEBHOOK_PUBLIC_BASE must be https://...")
        if not cert or not key:
            raise RuntimeError("SHERIFF_WEBHOOK_CERT and SHERIFF_WEBHOOK_KEY are required (https only)")

        _, l = await self.secrets.request("secrets.get_llm_bot_token", {})
        _, g = await self.secrets.request("secrets.get_gate_bot_token", {})
        llm_token = l.get("result", {}).get("token", "")
        sheriff_token = g.get("result", {}).get("token", "")

        if llm_token:
            requests.post(
                f"https://api.telegram.org/bot{llm_token}/setWebhook",
                json={
                    "url": f"{public_base}{cfg['llm_path']}",
                    "secret_token": cfg["llm_secret"],
                    "allowed_updates": ["message"],
                },
                timeout=20,
            )
        if sheriff_token:
            requests.post(
                f"https://api.telegram.org/bot{sheriff_token}/setWebhook",
                json={
                    "url": f"{public_base}{cfg['sheriff_path']}",
                    "secret_token": cfg["sheriff_secret"],
                    "allowed_updates": ["message"],
                },
                timeout=20,
            )

        service = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                path = self.path
                sec = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")

                role = None
                if path == cfg["llm_path"] and sec == cfg["llm_secret"]:
                    role = "llm"
                elif path == cfg["sheriff_path"] and sec == cfg["sheriff_secret"]:
                    role = "sheriff"

                if role is None:
                    self.send_response(403)
                    self.end_headers()
                    return

                try:
                    upd = json.loads(body.decode("utf-8"))
                except Exception:
                    self.send_response(400)
                    self.end_headers()
                    return

                msg = upd.get("message") or {}
                user_id = str((msg.get("from") or {}).get("id") or "")
                chat_id = (msg.get("chat") or {}).get("id")
                text = (msg.get("text") or "").strip()

                if user_id and chat_id is not None and text:
                    token = llm_token if role == "llm" else sheriff_token
                    if role == "llm":
                        __import__("asyncio").run(service._handle_ai_message(token, user_id, int(chat_id), text))
                    else:
                        __import__("asyncio").run(service._handle_sheriff_message(token, user_id, int(chat_id), text))

                self.send_response(200)
                self.end_headers()

            def log_message(self, format, *args):
                return

        httpd = ThreadingHTTPServer(("0.0.0.0", int(cfg["port"])), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=cert, keyfile=key)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)

        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()

        while True:
            await __import__("asyncio").sleep(2)
