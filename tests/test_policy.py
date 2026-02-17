import socket
import pytest
from shared.policy import GatewayPolicy

def test_validate_host_allowlist(monkeypatch):
    # Mock DNS to return a safe public IP
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_, **__: [(None, None, None, None, ("93.184.216.34", 0))])

    policy = GatewayPolicy(allowed_hosts={"api.github.com"})

    # Should not raise
    policy.validate_host("api.github.com")

    # Should raise for non-allowlisted
    with pytest.raises(ValueError, match="host not allowlisted"):
        policy.validate_host("example.com")

def test_reject_private_dns_resolution(monkeypatch):
    # Mock DNS to return a private IP
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_, **__: [(None, None, None, None, ("10.0.0.2", 0))])

    policy = GatewayPolicy(allowed_hosts={"intranet.local"})

    # Even if allowed by name, IP check should fail
    with pytest.raises(ValueError, match="private/link-local"):
        policy.validate_host("intranet.local")

def test_reject_loopback(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_, **__: [(None, None, None, None, ("127.0.0.1", 0))])
    policy = GatewayPolicy(allowed_hosts={"localhost"})

    with pytest.raises(ValueError, match="private/link-local"):
        policy.validate_host("localhost")