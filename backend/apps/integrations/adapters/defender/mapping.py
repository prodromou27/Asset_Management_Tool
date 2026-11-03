"""Defender for Endpoint machine → adapter-neutral source record + security state.

Identity fields (DNS name, OS, Entra device ID, NIC MACs/IPs) go through the shared
observation pipeline. Security facts (onboarding, sensor health, exposure, risk, tags,
first/last seen) are kept as original values under ``raw.fields`` and stored separately
in ``apps.security.EndpointSecurityState``; they never become asset fields.

``lastSeen`` is the time Defender last received data from the device. It is the
observation time, not a real-time online status, and it is excluded from the checksum
(``_meta``) so a device that merely reports in again is not a new observation. A change
in onboarding status, sensor health, exposure, risk or tags is a real change.
"""

import ipaddress
import re
from datetime import UTC, datetime

from apps.assets import network

# Original values kept as provenance (everything used except the volatile lastSeen,
# lastIpAddress and lastExternalIpAddress).
PROVENANCE = (
    "id",
    "computerDnsName",
    "osPlatform",
    "osVersion",
    "osBuild",
    "osArchitecture",
    "version",
    "firstSeen",
    "aadDeviceId",
    "isAadJoined",
    "onboardingStatus",
    "healthStatus",
    "exposureLevel",
    "riskScore",
    "machineTags",
    "rbacGroupName",
    "managedBy",
    "deviceValue",
    "vmMetadata",
)
_FRACTION = re.compile(r"(\.\d+)")
_NEVER = "0001-01-01"


def _text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_time(value) -> str | None:
    text = _text(value)
    if not text or text.startswith(_NEVER):
        return None
    text = _FRACTION.sub(lambda m: m.group(1)[:7], text)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)  # the API reports UTC
    return parsed.isoformat()


def device_type(os_platform: str | None, vm_metadata) -> str | None:
    if isinstance(vm_metadata, dict) and any(vm_metadata.values()):
        return "virtual_machine"
    if "server" in (os_platform or "").lower():
        return "server"
    return None  # Defender reports no chassis: the reviewer decides


def _hostname(name: str | None) -> str | None:
    if not name:
        return None
    try:
        return network.normalize_hostname(name)
    except ValueError:
        return None


def _usable_ip(value) -> str | None:
    try:
        address = ipaddress.ip_address(str(value).strip())
    except ValueError:
        return None
    if address.is_loopback or address.is_link_local or address.is_unspecified:
        return None
    return str(address)


def _interfaces(rows) -> list[dict]:
    """ipAddresses[] (one row per address) → one interface per MAC."""
    by_mac: dict[str, dict] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        mac = _text(row.get("macAddress"))
        if not mac or set(re.sub(r"\W", "", mac)) == {"0"}:
            continue
        key = mac.lower()
        if key not in by_mac:
            kind = re.sub(r"[^A-Za-z0-9 ]", "", str(row.get("type") or "Adapter"))[:40]
            by_mac[key] = {"name": f"{kind or 'Adapter'} {len(by_mac) + 1}", "mac": mac, "ips": []}
        ip = _usable_ip(row.get("ipAddress"))
        if ip and ip not in by_mac[key]["ips"]:
            by_mac[key]["ips"].append(ip)
    return list(by_mac.values())


def machine_to_record(row: dict, *, tenant_id: str, fetched_at: str) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    get = {k.lower(): v for k, v in row.items()}.get  # tolerate key-case drift

    external_id = _text(get("id"))
    last_seen = parse_time(get("lastseen"))
    first_seen = parse_time(get("firstseen"))
    observed_at = last_seen or first_seen
    if observed_at is None:
        observed_at = fetched_at
        warnings.append("Defender reports no first or last seen time; using the sync time.")
    elif last_seen is None:
        warnings.append("Defender reports no last seen time; using the first seen time.")

    dns = _text(get("computerdnsname"))
    hostname = _hostname(dns)
    if dns and not hostname:
        warnings.append(f"Ignored invalid DNS name {dns[:80]!r}.")
    os_platform, os_version, os_build = (
        _text(get("osplatform")),
        _text(get("osversion")),
        _text(get("osbuild")),
    )
    if os_version and os_build and str(os_build) not in os_version:
        os_version = f"{os_version} (build {os_build})"
    elif not os_version and os_build:
        os_version = str(os_build)

    entra_id = _text(get("aaddeviceid"))
    fields = {}
    for key in PROVENANCE:
        value = get(key.lower())
        if value is not None and value != "":
            fields[key] = value

    record = {
        "external_id": external_id,
        "observed_at": observed_at,
        "hostname": hostname,
        "interfaces": _interfaces(get("ipaddresses")),
        "os_name": os_platform,
        "os_version": os_version,
        "entra_device_id": entra_id,
        "device_type": device_type(os_platform, get("vmmetadata")),
        "source_version": _text(get("version")),
        "raw": {
            "tenant_id": tenant_id,
            "machine_id": external_id,
            "entra_device_id": entra_id,
            "fields": dict(sorted(fields.items())),
        },
        "_meta": {
            "last_seen": last_seen,
            "last_ip_address": _text(get("lastipaddress")),
            "fetched_at": fetched_at,
            "warnings": warnings,
        },
    }
    return record, warnings


def _list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(v).strip()[:100] for v in value if str(v).strip()})[:50]


def security_state(record: dict) -> dict:
    """Columns for EndpointSecurityState from a record built by machine_to_record."""
    raw = record.get("raw") or {}
    fields = raw.get("fields") or {}

    def short(key, limit=60):
        value = fields.get(key)
        return str(value)[:limit] if value not in (None, "") else ""

    def when(value):
        return datetime.fromisoformat(value) if value else None

    return {
        "tenant_id": str(raw.get("tenant_id") or "")[:100],
        "entra_device_id": str(record.get("entra_device_id") or "")[:36],
        "computer_dns_name": short("computerDnsName", 253),
        "os_platform": short("osPlatform", 100),
        "os_version": str(record.get("os_version") or "")[:100],
        "onboarding_status": short("onboardingStatus"),
        "health_status": short("healthStatus"),
        "exposure_level": short("exposureLevel"),
        "risk_score": short("riskScore"),
        "device_tags": _list(fields.get("machineTags")),
        "machine_group": short("rbacGroupName", 200),
        "first_seen_at": when(parse_time(fields.get("firstSeen"))),
        "last_seen_at": when((record.get("_meta") or {}).get("last_seen")),
        "original": fields,
    }
