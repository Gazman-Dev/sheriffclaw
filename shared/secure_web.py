from __future__ import annotations

import json
import urllib.parse
import urllib.request

from shared.policy import GatewayPolicy

SECRET_HEADERS = {"authorization", "x-api-key"}
ALLOWED_HEADERS = {"accept", "content-type", "user-agent"}


class SecureWebRequester:
    def __init__(self, policy: GatewayPolicy):
        self.policy = policy

    def request_https(self, payload: dict, resolved_secret_headers: dict[str, str]) -> dict:
        method = payload.get("method", "GET").upper()
        host = payload["host"]
        path = payload.get("path", "/")
        query = payload.get("query") or {}
        self.policy.validate_host(host)

        headers = {}
        for k, v in (payload.get("headers") or {}).items():
            lk = k.lower()
            if lk in ALLOWED_HEADERS:
                headers[k] = v
        for k, v in resolved_secret_headers.items():
            if k.lower() in SECRET_HEADERS:
                headers[k] = v

        url = f"https://{host}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = payload.get("body")
        data_bytes = None if data is None else (data.encode("utf-8") if isinstance(data, str) else json.dumps(data).encode("utf-8"))
        req = urllib.request.Request(url, method=method, headers=headers, data=data_bytes)
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
            body = resp.read()
            return {
                "status": resp.status,
                "headers": dict(resp.headers.items()),
                "body": body.decode("utf-8", errors="replace"),
                "bytes": len(body),
            }
