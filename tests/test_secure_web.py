import socket
import urllib.request

import pytest

from python_openclaw.gateway.policy import GatewayPolicy
from python_openclaw.gateway.secure_web import SecureWebConfig, SecureWebError, SecureWebRequester
from python_openclaw.gateway.secrets.store import SecretStore


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
    store = SecretStore(tmp_path / "secrets.enc")
    store.unlock("pw")
    store.set_secret("github", "Bearer token-123")
    policy = GatewayPolicy(allowed_hosts={"api.github.com"})
    config = SecureWebConfig(header_allowlist={"accept", "content-type"}, auth_host_permissions={"github": {"api.github.com"}})
    return SecureWebRequester(policy, store, config)


def test_no_secret_in_url(tmp_path, monkeypatch):
    requester = _make_requester(tmp_path, monkeypatch)
    with pytest.raises(SecureWebError):
        requester.request({"method": "GET", "host": "api.github.com", "path": "/users/{github}"})


def test_auth_injection_and_authorization_override_blocked(tmp_path, monkeypatch):
    requester = _make_requester(tmp_path, monkeypatch)
    opener = DummyOpener()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: opener)

    requester.request(
        {
            "method": "GET",
            "host": "api.github.com",
            "path": "/user",
            "headers": {"Authorization": "bad", "accept": "application/json", "x-other": "ignored"},
            "auth_handle": "github",
            "approval_token": "tok",
        }
    )
    assert opener.last_request.headers["Authorization"] == "Bearer token-123"
    assert "x-other" not in {k.lower() for k in opener.last_request.headers.keys()}


def test_auth_handle_host_restriction(tmp_path, monkeypatch):
    requester = _make_requester(tmp_path, monkeypatch)
    with pytest.raises(SecureWebError):
        requester.request(
            {
                "method": "GET",
                "host": "api.github.com",
                "path": "/user",
                "auth_handle": "other",
                "approval_token": "tok",
            }
        )


def test_reject_http_scheme(tmp_path, monkeypatch):
    requester = _make_requester(tmp_path, monkeypatch)
    with pytest.raises(SecureWebError):
        requester.request({"scheme": "http", "method": "GET", "host": "api.github.com", "path": "/user"})
