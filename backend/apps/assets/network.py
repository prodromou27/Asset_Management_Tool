"""Normalisation and validation of manually entered network identifiers.

None of these are required, and none are globally unique (docs/03): the same IP,
MAC or hostname may appear on several assets over time.
"""

import ipaddress
import re

_MAC_SEPARATORS = re.compile(r"[:\-.]")
_MAC_DIGITS = re.compile(r"[0-9a-f]{12}")
_HOST_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
# Includes ( ) # + , for OS adapter names such as "Intel(R) Ethernet Connection (7) #2".
_INTERFACE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/()#+,-]{0,63}$")


def normalize_mac(value: str) -> str:
    raw = value.strip().lower()
    if not raw:
        return ""
    digits = _MAC_SEPARATORS.sub("", raw)
    if not _MAC_DIGITS.fullmatch(digits):
        raise ValueError("Enter a MAC address like aa:bb:cc:dd:ee:ff.")
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def normalize_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError as exc:
        raise ValueError("Enter a valid IPv4 or IPv6 address.") from exc


def normalize_hostname(value: str) -> str:
    host = value.strip().lower().rstrip(".")
    if not host or len(host) > 253 or not all(_HOST_LABEL.match(p) for p in host.split(".")):
        raise ValueError("Enter a valid hostname (letters, digits, hyphens and dots).")
    return host


def validate_interface_name(value: str) -> str:
    name = value.strip()
    if not _INTERFACE_NAME.match(name):
        raise ValueError("Use up to 64 letters, digits, spaces or . _ : / ( ) # + , -")
    return name
