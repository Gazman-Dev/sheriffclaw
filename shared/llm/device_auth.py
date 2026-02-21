from __future__ import annotations

import json
import os
import select
import sys
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus

import requests

ISSUER = "https://auth.openai.com"
API_BASE = "https://auth.openai.com/api/accounts"
VERIFY_URL = "https://auth.openai.com/codex/device"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"


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


def _expires_at_from_response(data: dict[str, Any]) -> str | None:
    exp = data.get("expires_in")
    if isinstance(exp, (int, float)):
        return (datetime.now(timezone.utc) + timedelta(seconds=int(exp))).isoformat()
    return None


def _pending_poll_response(resp: requests.Response) -> bool:
    if resp.status_code in (202, 204):
        return True
    if resp.status_code in (400, 401, 403):
        try:
            data = resp.json()
        except Exception:
            data = {}
        err = str(data.get("error") or data.get("code") or "").lower()
        msg = str(data.get("message") or "").lower()
        pending_markers = ["authorization_pending", "pending", "slow_down", "not yet"]
        if any(m in err or m in msg for m in pending_markers):
            return True
    return False


def run_device_code_login(timeout_seconds: int = 900) -> DeviceAuthTokens:
    r = requests.post(
        f"{API_BASE}/deviceauth/usercode",
        headers={"Content-Type": "application/json"},
        json={"client_id": CLIENT_ID},
        timeout=30,
    )
    if r.status_code == 404:
        raise DeviceAuthNotEnabled("device code auth not enabled for this account/workspace")
    r.raise_for_status()
    data = r.json()
    device_auth_id = data["device_auth_id"]
    user_code = data["user_code"]
    interval = int(data.get("interval") or 5)

    full_url = f"{VERIFY_URL}?code={quote_plus(user_code)}"
    print(f"Open this URL: {full_url}")
    print(f"Code (already embedded in URL): {user_code}")
    try:
        opened = webbrowser.open(full_url)
        if opened:
            print("Opened browser automatically.")
        else:
            print("Could not auto-open browser. Please open the URL manually.")
    except Exception:
        print("Could not auto-open browser. Please open the URL manually.")

    print("Press Esc to cancel waiting.")

    start = time.time()
    authorization_code = None
    code_verifier = None

    fd = None
    old_term = None
    if sys.stdin.isatty():
        try:
            import termios
            import tty

            fd = sys.stdin.fileno()
            old_term = termios.tcgetattr(fd)
            tty.setcbreak(fd)
        except Exception:
            fd = None
            old_term = None

    try:
        while time.time() - start < timeout_seconds:
            if fd is not None:
                readable, _, _ = select.select([fd], [], [], 0)
                if readable:
                    ch = os.read(fd, 1)
                    if ch == b"\x1b":
                        raise RuntimeError("device auth cancelled by user")

            p = requests.post(
                f"{API_BASE}/deviceauth/token",
                headers={"Content-Type": "application/json"},
                json={"device_auth_id": device_auth_id, "user_code": user_code},
                timeout=30,
            )
            if _pending_poll_response(p):
                time.sleep(interval)
                continue
            if p.status_code == 404:
                raise DeviceAuthNotEnabled("device code auth not enabled for this account/workspace")
            if p.status_code >= 400:
                try:
                    detail = p.json()
                except Exception:
                    detail = p.text
                raise RuntimeError(f"device auth token polling failed: {p.status_code} {detail}")

            pd = p.json()
            authorization_code = pd.get("authorization_code")
            code_verifier = pd.get("code_verifier")
            if authorization_code and code_verifier:
                break
            time.sleep(interval)
    finally:
        if fd is not None and old_term is not None:
            try:
                import termios

                termios.tcsetattr(fd, termios.TCSADRAIN, old_term)
            except Exception:
                pass

    if not authorization_code or not code_verifier:
        raise RuntimeError("device auth timed out")

    t = requests.post(
        f"{ISSUER}/oauth/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": "https://auth.openai.com/deviceauth/callback",
            "client_id": CLIENT_ID,
            "code_verifier": code_verifier,
        },
        timeout=30,
    )
    t.raise_for_status()
    td = t.json()
    return DeviceAuthTokens(
        access_token=td["access_token"],
        refresh_token=td.get("refresh_token"),
        id_token=td.get("id_token"),
        obtained_at=_iso_now(),
        expires_at=_expires_at_from_response(td),
    )


def refresh_access_token(refresh_token: str) -> DeviceAuthTokens:
    t = requests.post(
        f"{ISSUER}/oauth/token",
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
        expires_at=_expires_at_from_response(td),
    )
