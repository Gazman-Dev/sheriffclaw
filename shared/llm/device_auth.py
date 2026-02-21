from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlencode, urlparse

import requests

ISSUER = "https://auth.openai.com"
AUTHORIZE_ENDPOINT = f"{ISSUER}/oauth/authorize"
TOKEN_ENDPOINT = f"{ISSUER}/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REDIRECT_URI = "http://localhost:1455/auth/callback"
SCOPE = "openid profile email offline_access"


@dataclass
class DeviceAuthTokens:
    access_token: str
    refresh_token: str | None
    id_token: str | None
    obtained_at: str
    expires_at: str | None


class DeviceAuthNotEnabled(RuntimeError):
    pass


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _jwt_exp_to_iso(token: str | None) -> str | None:
    if not token:
        return None
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("utf-8")))
        exp = payload.get("exp")
        if isinstance(exp, (int, float)):
            return datetime.fromtimestamp(int(exp), tz=timezone.utc).isoformat()
    except Exception:
        return None
    return None


def _make_pkce() -> tuple[str, str, str]:
    code_verifier = _b64url(secrets.token_bytes(64))
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = _b64url(digest)
    state = _b64url(secrets.token_bytes(24))
    return code_verifier, code_challenge, state


def _build_authorize_url(code_challenge: str, state: str) -> str:
    q = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    return f"{AUTHORIZE_ENDPOINT}?{urlencode(q)}"


def _exchange_code_for_tokens(code: str, code_verifier: str) -> dict[str, Any]:
    t = requests.post(
        TOKEN_ENDPOINT,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "code_verifier": code_verifier,
        },
        timeout=30,
    )
    t.raise_for_status()
    return t.json()


def run_browser_oauth_login(timeout_seconds: int = 900) -> DeviceAuthTokens:
    code_verifier, code_challenge, expected_state = _make_pkce()
    auth_url = _build_authorize_url(code_challenge, expected_state)

    result: dict[str, Any] = {"code": None, "state": None, "error": None}
    done = threading.Event()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/auth/callback":
                self.send_response(404)
                self.end_headers()
                return

            qs = parse_qs(parsed.query)
            result["code"] = (qs.get("code") or [None])[0]
            result["state"] = (qs.get("state") or [None])[0]
            result["error"] = (qs.get("error") or [None])[0]
            done.set()

            ok = result["error"] is None and result["code"] is not None and result["state"] == expected_state
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if ok:
                self.wfile.write(b"<html><body><h2>Sign-in successful. You can return to the terminal.</h2></body></html>")
            else:
                self.wfile.write(b"<html><body><h2>Sign-in failed. Return to the terminal.</h2></body></html>")

        def log_message(self, format, *args):  # noqa: A003
            return

    server = HTTPServer(("127.0.0.1", 1455), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print(f"Open this URL: {auth_url}")
    is_remote = bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT") or os.environ.get("CODESPACES"))
    if is_remote:
        print("Detected remote environment. Use SSH port forwarding for callback:")
        print("  ssh -L 1455:localhost:1455 user@remote")
    else:
        print("If browser and CLI are on different machines, use SSH forwarding:")
        print("  ssh -L 1455:localhost:1455 user@remote")

    try:
        opened = webbrowser.open(auth_url)
        if opened:
            print("Opened browser automatically.")
        else:
            print("Could not auto-open browser. Please open the URL manually.")
    except Exception:
        print("Could not auto-open browser. Please open the URL manually.")

    if not done.wait(timeout_seconds):
        server.shutdown()
        server.server_close()
        raise RuntimeError("browser OAuth login timed out")

    server.shutdown()
    server.server_close()

    if result.get("error"):
        raise RuntimeError(f"oauth authorize error: {result['error']}")
    if result.get("state") != expected_state:
        raise RuntimeError("oauth state mismatch")
    if not result.get("code"):
        raise RuntimeError("missing authorization code")

    td = _exchange_code_for_tokens(str(result["code"]), code_verifier)
    return DeviceAuthTokens(
        access_token=td["access_token"],
        refresh_token=td.get("refresh_token"),
        id_token=td.get("id_token"),
        obtained_at=_iso_now(),
        expires_at=_jwt_exp_to_iso(td.get("id_token")),
    )


def refresh_access_token(refresh_token: str) -> DeviceAuthTokens:
    t = requests.post(
        TOKEN_ENDPOINT,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
        },
        timeout=30,
    )
    t.raise_for_status()
    td = t.json()
    return DeviceAuthTokens(
        access_token=td["access_token"],
        refresh_token=td.get("refresh_token", refresh_token),
        id_token=td.get("id_token"),
        obtained_at=_iso_now(),
        expires_at=_jwt_exp_to_iso(td.get("id_token")),
    )
