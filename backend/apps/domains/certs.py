"""Names, certificate parsing and expiry status (no network access here)."""

import hashlib
import ipaddress
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed448, ed25519, rsa
from cryptography.x509.oid import ExtensionOID, NameOID
from django.conf import settings

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
MAX_UPLOAD_CERTIFICATES = 10


class InvalidName(ValueError):
    pass


def normalize_fqdn(value: str, *, allow_wildcard: bool = False) -> str:
    """Lower-case IDNA host name; refuses URLs, ports, paths and single labels."""
    raw = (value or "").strip().rstrip(".")
    if not raw:
        raise InvalidName("Enter a domain name.")
    if any(c in raw for c in "/:@?# \\"):
        raise InvalidName("Enter a name only, without scheme, port or path.")
    try:
        name = raw.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise InvalidName("This is not a valid domain name.") from exc
    labels = name.split(".")
    if allow_wildcard and labels[0] == "*":
        labels = labels[1:]
    if len(name) > 253 or len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
        raise InvalidName("This is not a valid fully qualified domain name.")
    if labels[-1].isdigit():
        raise InvalidName("This is not a valid fully qualified domain name.")
    return name


def normalize_host(value: str) -> str:
    """FQDN or IP literal (an approved endpoint host)."""
    raw = (value or "").strip().strip("[]")
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return normalize_fqdn(raw)


def is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


# --- Certificates ---------------------------------------------------------------------------


class CertificateError(ValueError):
    pass


def _name(name: x509.Name) -> str:
    return name.rfc4514_string()[:1000]


def _cn(name: x509.Name) -> str:
    values = name.get_attributes_for_oid(NameOID.COMMON_NAME)
    return str(values[0].value)[:300] if values else ""


def _key(cert: x509.Certificate) -> str:
    key = cert.public_key()
    if isinstance(key, rsa.RSAPublicKey):
        return f"RSA {key.key_size}"
    if isinstance(key, ec.EllipticCurvePublicKey):
        return f"EC {key.curve.name}"
    if isinstance(key, ed25519.Ed25519PublicKey):
        return "Ed25519"
    if isinstance(key, ed448.Ed448PublicKey):
        return "Ed448"
    if isinstance(key, dsa.DSAPublicKey):
        return f"DSA {key.key_size}"
    return "Other"


def _sans(cert: x509.Certificate) -> list[str]:
    try:
        ext = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    except x509.ExtensionNotFound:
        return []
    names = [str(n).lower() for n in ext.get_values_for_type(x509.DNSName)]
    names += [str(ip) for ip in ext.get_values_for_type(x509.IPAddress)]
    return names[:500]


def _is_ca(cert: x509.Certificate) -> bool:
    try:
        return bool(cert.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value.ca)
    except x509.ExtensionNotFound:
        return False


def describe(cert: x509.Certificate) -> dict:
    der = cert.public_bytes(serialization.Encoding.DER)
    try:
        algorithm = cert.signature_algorithm_oid._name  # noqa: SLF001 - readable OID name
    except Exception:  # pragma: no cover - unusual OIDs
        algorithm = cert.signature_algorithm_oid.dotted_string
    return {
        "fingerprint_sha256": hashlib.sha256(der).hexdigest(),
        "subject": _name(cert.subject),
        "common_name": _cn(cert.subject),
        "issuer": _name(cert.issuer),
        "serial_number": format(cert.serial_number, "x")[:100],
        "sans": _sans(cert),
        "not_before": cert.not_valid_before_utc,
        "not_after": cert.not_valid_after_utc,
        "signature_algorithm": str(algorithm)[:100],
        "public_key": _key(cert),
        "self_signed": cert.subject == cert.issuer,
        "is_ca": _is_ca(cert),
        "pem": cert.public_bytes(serialization.Encoding.PEM).decode("ascii"),
    }


def from_der(der: bytes) -> dict:
    try:
        return describe(x509.load_der_x509_certificate(der))
    except ValueError as exc:
        raise CertificateError("The endpoint presented a certificate ITAM cannot read.") from exc


def parse_upload(text: str) -> list[dict]:
    """Public certificates from pasted PEM. Private keys are refused, never stored."""
    if "PRIVATE KEY" in text:
        raise CertificateError(
            "This contains a private key. Upload the public certificate only; never paste "
            "private keys into ITAM."
        )
    if "BEGIN CERTIFICATE" not in text:
        raise CertificateError("Paste one or more PEM certificates (-----BEGIN CERTIFICATE-----).")
    try:
        certs = x509.load_pem_x509_certificates(text.encode("ascii", "ignore"))
    except ValueError as exc:
        raise CertificateError("The certificate could not be read.") from exc
    if len(certs) > MAX_UPLOAD_CERTIFICATES:
        raise CertificateError(f"Upload at most {MAX_UPLOAD_CERTIFICATES} certificates at once.")
    return [describe(c) for c in certs]


def hostname_matches(name: str, sans: list[str], common_name: str = "") -> bool:
    """RFC 6125-style match against SAN DNS/IP entries (CN only when there are no SANs)."""
    name = name.lower().rstrip(".")
    candidates = sans or ([common_name.lower()] if common_name else [])
    for pattern in candidates:
        if pattern == name:
            return True
        if pattern.startswith("*.") and not is_ip(name):
            suffix = pattern[1:]
            head, _, rest = name.partition(".")
            if head and "." + rest == suffix:
                return True
    return False


# --- Expiry status ---------------------------------------------------------------------------


def warning_days() -> list[int]:
    return sorted(set(settings.ITAM_CERT_WARNING_DAYS), reverse=True) or [90]


@dataclass
class Expiry:
    status: str  # unknown | ok | expiring | expired
    days_remaining: int | None
    threshold: int | None  # the smallest warning threshold reached (90/60/30/14/7)


def expiry(end: date | datetime | None, today: date) -> Expiry:
    """Status for a calendar end date (UTC); the last day still counts as valid."""
    if end is None:
        return Expiry("unknown", None, None)
    last = end.astimezone(UTC).date() if isinstance(end, datetime) else end
    days = (last - today).days
    if days < 0:
        return Expiry("expired", days, None)
    reached = [d for d in warning_days() if days <= d]
    if reached:
        return Expiry("expiring", days, min(reached))
    return Expiry("ok", days, None)
