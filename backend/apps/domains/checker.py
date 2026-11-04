"""Read the certificate presented by one approved TLS endpoint (docs/06, docs/14 SSRF row).

Only ``TlsEndpoint`` rows registered by an administrator are ever contacted, on their own
host and port. The host is resolved once and the connection goes to that address (DNS pin),
so a later DNS answer cannot redirect the check. Metadata, link-local, multicast, reserved
and unspecified addresses are always refused; loopback only when a test setting allows it.
Raw TLS only: no HTTP request, no redirects, nothing is sent after the handshake. The
certificate is read without trusting it (expired or self-signed certificates must still be
inventoried); TLS 1.2 is the minimum protocol (docs/14).
"""

import ipaddress
import socket
import ssl
from dataclasses import dataclass

from django.conf import settings

METADATA = {
    ipaddress.ip_address("169.254.169.254"),  # cloud instance metadata
    ipaddress.ip_address("fd00:ec2::254"),
    ipaddress.ip_address("100.100.100.200"),
}


class Blocked(Exception):
    pass


class CheckFailed(Exception):
    pass


@dataclass
class Presented:
    der: bytes
    address: str
    tls_version: str


def refused(address: str) -> str | None:
    """Why ITAM will not connect to this address, or None."""
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip in METADATA:
        return "cloud metadata address"
    if ip.is_loopback:
        return None if settings.ITAM_TLS_ALLOW_LOOPBACK else "loopback address"
    if ip.is_link_local:
        return "link-local address"
    if ip.is_multicast:
        return "multicast address"
    if ip.is_unspecified:
        return "unspecified address"
    if ip.is_reserved:
        return "reserved address"
    return None


def resolve(host: str, port: int) -> str:
    """One allowed address for host (all answers must be allowed: no mixed tricks)."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise CheckFailed("The host name does not resolve.") from exc
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not addresses:
        raise CheckFailed("The host name does not resolve.")
    for address in addresses:
        if reason := refused(address):
            raise Blocked(f"{host} resolves to {address} ({reason}); ITAM does not connect there.")
    return addresses[0]


def _context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # Inventory, not trust: read whatever certificate is presented. Hostname match is
    # evaluated separately from the certificate's SANs.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def fetch(host: str, port: int, sni: str) -> Presented:
    address = resolve(host, port)
    timeout = settings.ITAM_TLS_CHECK_TIMEOUT_SECONDS
    try:
        with socket.create_connection((address, port), timeout=timeout) as sock:
            with _context().wrap_socket(sock, server_hostname=sni or None) as tls:
                der = tls.getpeercert(binary_form=True)
                version = tls.version() or ""
    except TimeoutError as exc:
        raise CheckFailed(f"No answer from {address}:{port} within {timeout} s.") from exc
    except ssl.SSLError as exc:
        raise CheckFailed(f"TLS handshake failed ({exc.reason or 'protocol error'}).") from exc
    except ConnectionRefusedError as exc:
        raise CheckFailed(f"Connection refused by {address}:{port}.") from exc
    except OSError as exc:
        raise CheckFailed(
            f"Could not connect to {address}:{port} ({exc.strerror or exc})."
        ) from exc
    if not der:
        raise CheckFailed("The endpoint presented no certificate.")
    return Presented(der=der, address=address, tls_version=version)
