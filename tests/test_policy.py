import socket
import pytest
from shared.policy import GatewayPolicy

def test_validate_host_only_checks_dns_safety(monkeypatch):
    # Mock DNS to return a safe public IP
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_, **__: [(None, None, None, None, ("93.184.216.34", 0))])

    policy = GatewayPolicy()

    # Should not raise for arbitrary domains (allowlist removed)
    policy.validate_host("api.github.com")
    policy.validate_host("example.com")
    policy.validate_host("random-unknown.org")

def test_reject_private_dns_resolution(monkeypatch):
    # Mock DNS to return a private IP
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_, **__: [(None, None, None, None, ("10.0.0.2", 0))])

    policy = GatewayPolicy()

    # Even if allowed by name, IP check should fail
    with pytest.raises(ValueError, match="private/link-local"):
        policy.validate_host("intranet.local")

def test_reject_loopback(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_, **__: [(None, None, None, None, ("127.0.0.1", 0))])
    policy = GatewayPolicy()

    with pytest.raises(ValueError, match="private/link-local"):
        policy.validate_host("localhost")