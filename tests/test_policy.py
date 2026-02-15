import socket

import pytest

from python_openclaw.gateway.policy import GatewayPolicy, PolicyViolation


def test_reject_non_allowlisted_host(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [(None, None, None, None, ("93.184.216.34", 0))])
    policy = GatewayPolicy(allowed_hosts={"api.github.com"})
    with pytest.raises(PolicyViolation):
        policy.validate_https_request("example.com", "/")


def test_reject_ip_literal_host():
    policy = GatewayPolicy(allowed_hosts={"93.184.216.34"})
    with pytest.raises(PolicyViolation):
        policy.validate_https_request("93.184.216.34", "/")


def test_reject_private_dns_resolution(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [(None, None, None, None, ("10.0.0.2", 0))])
    policy = GatewayPolicy(allowed_hosts={"api.github.com"})
    with pytest.raises(PolicyViolation):
        policy.validate_https_request("api.github.com", "/")


def test_redirect_disabled(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [(None, None, None, None, ("93.184.216.34", 0))])
    policy = GatewayPolicy(allowed_hosts={"api.github.com"}, redirect_enabled=False)
    with pytest.raises(PolicyViolation):
        policy.validate_redirect_target("api.github.com")
