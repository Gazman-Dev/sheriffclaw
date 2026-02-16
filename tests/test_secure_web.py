import socket
import urllib.request

import pytest

from python_openclaw.gateway.policy import GatewayPolicy
from python_openclaw.gateway.secure_web import SecureWebConfig, SecureWebError, SecureWebRequester
from python_openclaw.gateway.secrets.store import SecretStore
from python_openclaw.security.permissions import (
    PermissionDeniedException,
    PermissionEnforcer,
    PermissionStore,
    RESOURCE_DOMAIN,
    RESOURCE_DOMAIN_HEADER,
)


class DummyResponse:
    def __init__(self, status=200, body=b"ok", headers=None):
        self._status = status
        self._body = body
        self.headers = headers or {}

    def read(self):
        return self._body

    def getcode(self):
        return self._status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class DummyOpener:
    def __init__(self):
        self.last_request = None

    def open(self, req, timeout=0):
        self.last_request = req
        return DummyResponse(headers={"content-type": "text/plain"})


def _make_requester(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [(None, None, None, None, ("93.184.216.34", 0))])
    secret_store = SecretStore(tmp_path / "secrets.enc")
    secret_store.unlock("pw")
    secret_store.set_secret("github", "token-123")
    permission_store = PermissionStore(tmp_path / "permissions.db")
    enforcer = PermissionEnforcer(store=permission_store)
    requester = SecureWebRequester(
        GatewayPolicy(allowed_hosts={"api.github.com", "example.com"}),
        secret_store,
        SecureWebConfig(
            header_allowlist={"accept", "content-type"},
            secret_header_allowlist={"authorization", "x-api-key"},
            secret_handle_allowed_hosts={"github": {"api.github.com"}},
        ),
        permission_enforcer=enforcer,
    )
    return requester, permission_store


def test_rejects_secret_placeholder_in_path_or_query(tmp_path, monkeypatch):
    requester, _ = _make_requester(tmp_path, monkeypatch)
    with pytest.raises(SecureWebError):
        requester.request({"method": "GET", "host": "api.github.com", "path": "/users/{github}"})
    with pytest.raises(SecureWebError):
        requester.request({"method": "GET", "host": "api.github.com", "path": "/users", "query": {"q": "{github}"}})


def test_rejects_secret_placeholder_in_body(tmp_path, monkeypatch):
    requester, permission_store = _make_requester(tmp_path, monkeypatch)
    permission_store.set_decision("u1", RESOURCE_DOMAIN, "api.github.com", "ALLOW")
    with pytest.raises(SecureWebError):
        requester.request(
            {"method": "POST", "host": "api.github.com", "path": "/user", "body": {"raw": "{github}"}},
            principal_id="u1",
        )


def test_rejects_direct_authorization_header(tmp_path, monkeypatch):
    requester, permission_store = _make_requester(tmp_path, monkeypatch)
    permission_store.set_decision("u1", RESOURCE_DOMAIN, "api.github.com", "ALLOW")
    with pytest.raises(SecureWebError):
        requester.request(
            {
                "method": "GET",
                "host": "api.github.com",
                "path": "/user",
                "headers": {"Authorization": "Bearer abc"},
            },
            principal_id="u1",
        )


def test_injects_secret_only_from_secret_headers_mapping(tmp_path, monkeypatch):
    requester, permission_store = _make_requester(tmp_path, monkeypatch)
    permission_store.set_decision("u1", RESOURCE_DOMAIN, "api.github.com", "ALLOW")
    opener = DummyOpener()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: opener)

    requester.request(
        {
            "method": "POST",
            "host": "api.github.com",
            "path": "/user",
            "headers": {"accept": "application/json", "x-other": "{github}"},
            "secret_headers": {"Authorization": "github"},
            "body": {"ok": "body"},
        },
        principal_id="u1",
    )

    assert opener.last_request.headers["Authorization"] == "Bearer token-123"
    assert "x-other" not in {k.lower() for k in opener.last_request.headers.keys()}


def test_enforces_secret_handle_host_scoping(tmp_path, monkeypatch):
    requester, permission_store = _make_requester(tmp_path, monkeypatch)
    permission_store.set_decision("u1", RESOURCE_DOMAIN, "example.com", "ALLOW")
    with pytest.raises(SecureWebError):
        requester.request(
            {
                "method": "GET",
                "host": "example.com",
                "path": "/user",
                "secret_headers": {"Authorization": "github"},
            },
            principal_id="u1",
        )


def test_secret_headers_require_domain_header_approval(tmp_path, monkeypatch):
    requester, permission_store = _make_requester(tmp_path, monkeypatch)
    permission_store.set_decision("u1", RESOURCE_DOMAIN, "api.github.com", "ALLOW")
    with pytest.raises(PermissionDeniedException) as exc:
        requester.request(
            {
                "method": "GET",
                "host": "api.github.com",
                "path": "/user",
                "secret_headers": {"Authorization": "github", "X-Custom": "github"},
            },
            principal_id="u1",
        )
    assert exc.value.resource_type == RESOURCE_DOMAIN_HEADER
    assert exc.value.resource_value == "api.github.com|x-custom"
