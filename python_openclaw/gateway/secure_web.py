from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from python_openclaw.gateway.policy import GatewayPolicy, PolicyViolation
from python_openclaw.gateway.secrets.store import SecretStore
from python_openclaw.security.permissions import PermissionEnforcer


class SecureWebError(Exception):
    pass


@dataclass
class SecureWebConfig:
    header_allowlist: set[str]
    timeout_seconds: float = 10.0
    max_body_bytes: int = 64 * 1024


class SecureWebRequester:
    def __init__(self, policy: GatewayPolicy, secrets: SecretStore, config: SecureWebConfig, permission_enforcer: PermissionEnforcer | None = None) -> None:
        self.policy = policy
        self.secrets = secrets
        self.config = config
        self.permission_enforcer = permission_enforcer

    def request(self, payload: dict, *, principal_id: str | None = None) -> dict:
        method = payload["method"].upper()
        scheme = payload.get("scheme", "https")
        if scheme != "https":
            raise SecureWebError("https only")
        host = payload["host"]
        if principal_id and self.permission_enforcer:
            self.permission_enforcer.ensure_allowed(principal_id, "domain", host, {"path": payload.get("path")})
        path = payload["path"]
        query = payload.get("query") or {}
        headers = payload.get("headers") or {}
        body = payload.get("body")

        self.policy.validate_https_request(host, path)
        if _contains_secret_placeholder(path):
            raise SecureWebError("secret placeholder forbidden in path")
        for k, v in query.items():
            if _contains_secret_placeholder(str(k)) or _contains_secret_placeholder(str(v)):
                raise SecureWebError("secret placeholder forbidden in query")
        clean_headers = {}
        for hk, hv in headers.items():
            key = hk.lower()
            if key not in self.config.header_allowlist:
                continue
            clean_headers[hk] = self.secrets.inject_references(str(hv))

        encoded_query = urllib.parse.urlencode(query, doseq=True)
        url = f"https://{host}{path}" + (f"?{encoded_query}" if encoded_query else "")
        if len(url) > 4096:
            raise SecureWebError("url too long")
        data: bytes | None = None
        if body is not None:
            if isinstance(body, dict):
                data = json.dumps(body).encode("utf-8")
                clean_headers.setdefault("Content-Type", "application/json")
            elif isinstance(body, str):
                data = body.encode("utf-8")
            elif isinstance(body, (bytes, bytearray)):
                data = bytes(body)
            else:
                raise SecureWebError("unsupported body type")
            if len(data) > self.config.max_body_bytes:
                raise SecureWebError("body too large")

        req = urllib.request.Request(url=url, method=method, headers=clean_headers, data=data)
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(req, timeout=self.config.timeout_seconds) as response:
                resp_body = response.read()
                return {
                    "status": response.getcode(),
                    "headers": dict(response.headers.items()),
                    "body": resp_body.decode("utf-8", errors="replace"),
                    "bytes": len(resp_body),
                }
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location", "")
                self._validate_redirect(location)
            raise

    def _validate_redirect(self, location: str) -> None:
        parsed = urllib.parse.urlparse(location)
        if parsed.scheme and parsed.scheme != "https":
            raise PolicyViolation("redirect requires https")
        if not parsed.netloc:
            return
        host = parsed.hostname or ""
        self.policy.validate_redirect_target(host)


def body_summary(body: object) -> str:
    if body is None:
        return "none"
    raw = json.dumps(body, sort_keys=True).encode("utf-8") if not isinstance(body, (bytes, bytearray)) else bytes(body)
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return f"sha256:{digest};bytes={len(raw)}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _contains_secret_placeholder(value: str) -> bool:
    return bool(re.search(r"\{[a-zA-Z0-9_\-]+\}", value))
