from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from shared.policy import GatewayPolicy
from shared.paths import gw_root

SECRET_HEADERS = {"authorization", "x-api-key"}
ALLOWED_HEADERS = {"accept", "content-type", "user-agent"}


class SecureWebRequester:
    def __init__(self, policy: GatewayPolicy):
        self.policy = policy
        self.debug_mode = os.environ.get("SHERIFF_DEBUG", "").strip().lower() in {"1", "true", "yes"}

    def _append_debug_outbox(self, item: dict) -> None:
        p = gw_root() / "state" / "debug" / "web_outbox.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

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
        if self.debug_mode:
            self._append_debug_outbox({"method": method, "url": url, "headers": headers, "query": query, "body": payload.get("body")})
            return {"status": 200, "headers": {"content-type": "application/json"}, "body": "{\"debug_mock\": true}", "bytes": len("{\"debug_mock\": true}")}
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
