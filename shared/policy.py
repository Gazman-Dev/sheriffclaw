from __future__ import annotations

import ipaddress
import socket


class GatewayPolicy:
    def __init__(self, allowed_hosts: set[str]):
        self.allowed_hosts = allowed_hosts

    def validate_host(self, host: str) -> None:
        if host not in self.allowed_hosts:
            raise ValueError(f"host not allowlisted: {host}")
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            addr = info[4][0]
            ip = ipaddress.ip_address(addr)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                raise ValueError("host resolved to private/link-local address")
