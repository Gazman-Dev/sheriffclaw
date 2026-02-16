from __future__ import annotations

import asyncio
import json
import ssl
import subprocess
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from python_openclaw.gateway.master_password import verify_password


@dataclass
class UnlockDependencies:
    verify_record: dict
    unlock_callback: Callable[[str], None]


class UnlockCoordinator:
    def __init__(self, deps: UnlockDependencies, *, max_attempts: int = 5, window_seconds: int = 60):
        self.deps = deps
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def attempt_unlock(self, password: str, remote_ip: str = "127.0.0.1") -> dict[str, str]:
        now = time.time()
        history = self._attempts[remote_ip]
        while history and now - history[0] > self.window_seconds:
            history.popleft()
        if len(history) >= self.max_attempts:
            return {"status": "error", "error": "rate_limited"}

        history.append(now)
        if not verify_password(password, self.deps.verify_record):
            return {"status": "error", "error": "wrong_password"}

        self.deps.unlock_callback(password)
        history.clear()
        return {"status": "ok"}


def ensure_self_signed_cert(cert_path: Path, key_path: Path) -> None:
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    if cert_path.exists() and key_path.exists():
        return
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-nodes",
            "-days",
            "3650",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-subj",
            "/CN=openclaw-local",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def create_handler(coordinator: UnlockCoordinator):
    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: dict[str, str]) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            if self.path != "/":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            html = b"<html><body><h1>OpenClaw Unlock</h1><form method='post' action='/unlock'><input type='password' name='password'/><button type='submit'>Unlock</button></form></body></html>"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def do_POST(self):  # noqa: N802
            if self.path != "/unlock":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            password = ""
            ctype = self.headers.get("Content-Type", "")
            if "application/json" in ctype:
                try:
                    payload = json.loads(raw.decode("utf-8"))
                    password = str(payload.get("password", ""))
                except json.JSONDecodeError:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"status": "error", "error": "invalid_json"})
                    return
            else:
                try:
                    from urllib.parse import parse_qs

                    password = parse_qs(raw.decode("utf-8")).get("password", [""])[0]
                except Exception:
                    password = ""
            result = coordinator.attempt_unlock(password, self.client_address[0])
            status = HTTPStatus.OK if result.get("status") == "ok" else HTTPStatus.UNAUTHORIZED
            self._send_json(status, result)

        def log_message(self, format: str, *args):
            return

    return Handler


async def run_unlock_server(
    coordinator: UnlockCoordinator,
    *,
    host: str = "127.0.0.1",
    port: int = 8443,
    cert_path: Path,
    key_path: Path,
    stop_event: asyncio.Event | None = None,
) -> None:
    ensure_self_signed_cert(cert_path, key_path)
    handler = create_handler(coordinator)
    server = ThreadingHTTPServer((host, port), handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    server.socket = context.wrap_socket(server.socket, server_side=True)

    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    thread.start()
    try:
        if stop_event is None:
            while True:
                await asyncio.sleep(3600)
        else:
            await stop_event.wait()
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
