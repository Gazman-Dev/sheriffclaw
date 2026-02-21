from __future__ import annotations

import json
import select
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

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

    print(f"Open this URL: {VERIFY_URL}")
    print(f"Enter this code: {user_code}")
    print("Press Enter to cancel waiting.")

    start = time.time()
    authorization_code = None
    code_verifier = None

    while time.time() - start < timeout_seconds:
        if sys.stdin.isatty():
            readable, _, _ = select.select([sys.stdin], [], [], 0)
            if readable:
                line = sys.stdin.readline()
                if line.strip() == "":
                    raise RuntimeError("device auth cancelled by user")

        p = requests.post(
            f"{API_BASE}/deviceauth/token",
            headers={"Content-Type": "application/json"},
            json={"device_auth_id": device_auth_id, "user_code": user_code},
            timeout=30,
        )
        if p.status_code in (202, 204, 400):
            time.sleep(interval)
            continue
        p.raise_for_status()
        pd = p.json()
        authorization_code = pd.get("authorization_code")
        code_verifier = pd.get("code_verifier")
        if authorization_code and code_verifier:
            break
        time.sleep(interval)

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
