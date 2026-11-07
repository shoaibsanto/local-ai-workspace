"""SSRF (server-side request forgery) protection for outbound HTTP calls.

Local-first app, but it still makes outbound requests on the user's behalf:
to LLM providers and to remote MCP servers. Without guarding those, a
malicious or compromised provider/MCP config (or a config imported from
somewhere untrusted) could be used to probe or hit internal network services
and cloud metadata endpoints (e.g. 169.254.169.254) from the user's machine.

`validate_outbound_url` resolves the hostname to its actual IP address(es)
and checks *those* -- not just the hostname string -- which also guards
against DNS rebinding (a hostname that resolves to a public IP at
config-time but a private IP at request-time).

Local model endpoints (e.g. http://localhost:11434) are a legitimate,
common use case, so callers can pass `allow_loopback=True` to skip the
check entirely for configs the user explicitly opted into treating as
local/trusted (see ProviderConfig.allow_local / MCPServerConfig.allow_local).
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

# Cloud metadata endpoints that must always be blocked, even though some of
# them look like "just another IP" to a naive private-range check.
_BLOCKED_METADATA_IPS = {
    "169.254.169.254",  # AWS/GCP/Azure/OpenStack metadata
    "169.254.170.2",  # AWS ECS task metadata
    "fd00:ec2::254",  # AWS IMDSv2 IPv6 metadata endpoint
}


def _is_blocked_ip(ip_str: str) -> bool:
    if ip_str in _BLOCKED_METADATA_IPS:
        return True
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparsable -> treat as unsafe
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


def validate_outbound_url(url: str, allow_loopback: bool = False) -> None:
    """Raise ValueError if `url` targets a private/link-local/loopback/cloud
    metadata address, unless `allow_loopback` is True.

    Resolves DNS and validates the *resolved* IP addresses (all of them, if
    a hostname has multiple A/AAAA records), not just the hostname text, so
    a hostname that passes a naive string check but resolves to an internal
    address (DNS rebinding) is still caught.
    """
    if allow_loopback:
        return

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme for outbound request: {parsed.scheme!r}")

    host = parsed.hostname
    if not host:
        raise ValueError(f"URL has no hostname: {url!r}")

    # If the host is itself a literal IP, validate it directly.
    try:
        ipaddress.ip_address(host)
        literal_ips = [host]
    except ValueError:
        literal_ips = None

    if literal_ips is not None:
        resolved_ips = literal_ips
    else:
        try:
            addrinfo = socket.getaddrinfo(host, None)
        except socket.gaierror as e:
            raise ValueError(f"Could not resolve host {host!r}: {e}") from e
        resolved_ips = sorted({str(info[4][0]) for info in addrinfo})

    if not resolved_ips:
        raise ValueError(f"Host {host!r} resolved to no addresses")

    for ip_str in resolved_ips:
        if _is_blocked_ip(ip_str):
            raise ValueError(
                f"Refusing outbound request to {host!r} ({ip_str}): "
                "private/loopback/link-local/metadata address blocked by SSRF guard "
                "(set allow_local=True on this config if this is an intentional "
                "local endpoint)"
            )
