from __future__ import annotations

import ipaddress
import socket


class GatewayPolicy:
    def __init__(self) -> None:
        pass

    def validate_host(self, host: str) -> None:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as e:
            raise ValueError(f"host resolution failed: {host}") from e

        for info in infos:
            addr = info[4][0]
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                continue

            if ip.is_private or ip.is_loopback or ip.is_link_local:
                raise ValueError("host resolved to private/link-local address")