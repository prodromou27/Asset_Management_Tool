"""Shared connector errors and the HTTP safety checks every adapter uses."""

import ipaddress
import socket
from urllib.parse import urlparse


class SourceError(Exception):
    """A source request failed. `code` is stable for the UI; messages never contain secrets."""

    code = "SOURCE_ERROR"
    retryable = False


class AuthError(SourceError):
    code = "SOURCE_AUTH_FAILED"


class NotSupported(SourceError):
    code = "SOURCE_NOT_SUPPORTED"


class Unavailable(SourceError):
    code = "SOURCE_UNAVAILABLE"
    retryable = True


class UnsafeTarget(SourceError):
    code = "SOURCE_TARGET_REFUSED"


class LiveAccessDenied(SourceError):
    code = "LIVE_ACCESS_NOT_APPROVED"


def check_base_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise UnsafeTarget("The base URL must be an https:// URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise UnsafeTarget("The base URL must not contain credentials, a query or a fragment.")
    return url.rstrip("/")


def check_host_addresses(host: str, resolver=socket.getaddrinfo) -> None:
    """Refuse loopback, link-local (incl. cloud metadata 169.254.169.254), multicast,
    unspecified and reserved targets. Private ranges are allowed: LibreNMS is internal."""
    try:
        infos = resolver(host, 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise Unavailable(f"Cannot resolve {host}.") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_unspecified
            or address.is_reserved
        ):
            raise UnsafeTarget(f"{host} resolves to a disallowed address ({address}).")
