from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Iterable


class PolicyViolation(Exception):
    pass


@dataclass
class GatewayPolicy:
    allowed_hosts: set[str]
    redirect_enabled: bool = False

    def validate_https_request(self, host: str, path: str, *, is_redirect: bool = False) -> None:
        if not path.startswith("/"):
            raise PolicyViolation("path must start with /")
        if host not in self.allowed_hosts:
            raise PolicyViolation("host not allowlisted")
        if _is_ip_literal(host):
            raise PolicyViolation("ip literal hosts are forbidden")
        self._validate_dns(host)
        if is_redirect and not self.redirect_enabled:
            raise PolicyViolation("redirects disabled")

    def validate_redirect_target(self, host: str) -> None:
        if not self.redirect_enabled:
            raise PolicyViolation("redirects disabled")
        self.validate_https_request(host, "/", is_redirect=True)

    def _validate_dns(self, host: str) -> None:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if _is_private_or_reserved(ip):
                raise PolicyViolation("host resolves to private/reserved IP")


def _is_private_or_reserved(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_reserved
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
    )


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False
