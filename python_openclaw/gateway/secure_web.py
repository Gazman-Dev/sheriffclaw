from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from python_openclaw.gateway.policy import GatewayPolicy, PolicyViolation
from python_openclaw.gateway.secrets.store import SecretLockedError, SecretNotFoundError, SecretStore
from python_openclaw.security.permissions import PermissionEnforcer


class SecureWebError(Exception):
    pass


@dataclass
class SecureWebConfig:
    header_allowlist: set[str]
    secret_header_allowlist: set[str] = field(default_factory=lambda: {"authorization", "x-api-key"})
    secret_handle_allowed_hosts: dict[str, set[str]] = field(default_factory=dict)
    require_approval_for_secret_headers_outside_allowlist: bool = True
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
        path = payload["path"]
        query = payload.get("query") or {}
        headers = payload.get("headers") or {}
        secret_headers = payload.get("secret_headers") or {}
        auth_handle = payload.get("auth_handle")
        body = payload.get("body")

        self.policy.validate_https_request(host, path)
        if _contains_secret_placeholder(path):
            raise SecureWebError("secret placeholder forbidden in path")
        for k, v in query.items():
            if _contains_secret_placeholder(str(k)) or _contains_secret_placeholder(str(v)):
                raise SecureWebError("secret placeholder forbidden in query")

        if isinstance(payload.get("url"), str) and _contains_secret_placeholder(payload["url"]):
            raise SecureWebError("secret placeholder forbidden in url")

        clean_headers: dict[str, str] = {}
        for hk, hv in headers.items():
            key = hk.lower()
            if key == "authorization":
                raise SecureWebError("authorization header must use secret_headers")
            if key not in self.config.header_allowlist:
                continue
            clean_headers[hk] = str(hv)

        if auth_handle:
            secret_headers = {**secret_headers, "Authorization": auth_handle}

        secret_headers_normalized = {str(header).lower(): str(handle) for header, handle in secret_headers.items()}
        requires_domain_approval = bool(secret_headers_normalized)
        if any(header not in self.config.secret_header_allowlist for header in secret_headers_normalized):
            requires_domain_approval = requires_domain_approval or self.config.require_approval_for_secret_headers_outside_allowlist

        if principal_id and self.permission_enforcer:
            metadata = {"path": path, "method": method, "uses_secret_headers": bool(secret_headers_normalized)}
            if requires_domain_approval:
                self.permission_enforcer.ensure_allowed(principal_id, "domain", host, metadata)
            else:
                self.permission_enforcer.ensure_allowed(principal_id, "domain", host, {"path": path})

        for header, handle in secret_headers_normalized.items():
            self._validate_secret_handle_for_host(handle, host)
            secret_value = self._resolve_secret(handle)
            if header == "authorization":
                clean_headers["Authorization"] = f"Bearer {secret_value}"
            elif header == "x-api-key":
                clean_headers["X-API-Key"] = secret_value
            else:
                clean_headers[header] = secret_value

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
                raise SecureWebError(f"redirect blocked: {location or 'unknown'}")
            error_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            return {
                "status": exc.code,
                "headers": dict(exc.headers.items()) if exc.headers else {},
                "body": error_body,
                "bytes": len(error_body.encode("utf-8")),
            }
        except urllib.error.URLError as exc:
            raise SecureWebError(f"network error: {exc.reason}") from exc

    def _resolve_secret(self, handle: str) -> str:
        try:
            return self.secrets.get_secret(handle)
        except SecretNotFoundError:
            raise
        except SecretLockedError as exc:
            raise SecureWebError(str(exc)) from exc

    def _validate_secret_handle_for_host(self, handle: str, host: str) -> None:
        allowed_hosts = self.config.secret_handle_allowed_hosts.get(handle)
        if not allowed_hosts:
            raise SecureWebError(f"secret handle '{handle}' is not configured for web usage")
        if host not in allowed_hosts:
            raise SecureWebError(f"secret handle '{handle}' is not allowed for host {host}")

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
