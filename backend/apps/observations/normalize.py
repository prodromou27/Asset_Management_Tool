"""Normalisation of source records into comparable values.

Input is the adapter-neutral *source record* every connector will emit (documented
in docs/05 shared normalisation and fixtures/discovery/README.md):

    {
      "external_id": "317",                     # required, stable within the instance
      "observed_at": "2026-11-02T08:00:00Z",    # required, RFC 3339 with offset
      "manufacturer": "Cisco Systems, Inc.", "model": "C9300-48T", "serial": "FOC123",
      "hostname": "SW-CORE-01.corp.example",    # or "hostnames": [...]
      "interfaces": [{"name": "Vlan10", "mac": "0200.0000.0001", "ips": ["10.10.0.2"]}],
      "ip_addresses": [{"address": "10.10.0.2", "vrf": "", "interface": "Vlan10"}],
      "os_name": "IOS XE", "os_version": "17.9.4", "firmware_version": "17.9.4",
      "hardware_uuid": "…", "device_type": "switch", "source_version": "24.10"
    }

Values that cannot be trusted become None (unknown) and are listed in `warnings`;
they are never guessed.
"""

import hashlib
import json
import re
import uuid
from datetime import datetime

from apps.assets import network

NORMALIZER_VERSION = 1

MANUFACTURER_ALIASES = {
    "cisco systems": "Cisco",
    "cisco systems inc": "Cisco",
    "cisco": "Cisco",
    "hewlett-packard": "HP",
    "hewlett packard": "HP",
    "hp inc": "HP",
    "hp": "HP",
    "hewlett packard enterprise": "HPE",
    "hpe": "HPE",
    "aruba networks": "HPE Aruba",
    "dell inc": "Dell",
    "dell": "Dell",
    "lenovo": "Lenovo",
    "microsoft corporation": "Microsoft",
    "vmware inc": "VMware",
    "vmware": "VMware",
    "fortinet inc": "Fortinet",
    "fortinet": "Fortinet",
    "juniper networks": "Juniper",
    "apc by schneider electric": "APC",
    "american power conversion": "APC",
    "apc": "APC",
    "apple inc": "Apple",
    "samsung electronics": "Samsung",
    "huawei technologies": "Huawei",
}

# Firmware/BIOS defaults that are not real serial numbers.
PLACEHOLDER_SERIALS = {
    "",
    "0",
    "00000000",
    "none",
    "null",
    "n/a",
    "na",
    "unknown",
    "default string",
    "to be filled by o.e.m.",
    "to be filled by oem",
    "system serial number",
    "chassis serial number",
    "not specified",
    "not available",
    "123456789",
    "0123456789",
    "serial",
    "xxxxxxxxxx",
}

DEVICE_TYPE_TO_CATEGORY = {
    "switch": "networking-switch",
    "router": "networking-router",
    "access_point": "networking-access-point",
    "wireless_controller": "networking-wireless-controller",
    "load_balancer": "networking-load-balancer",
    "firewall": "security-firewall",
    "vpn": "security-vpn-gateway",
    "desktop": "workstations-desktop",
    "laptop": "workstations-laptop",
    "thin_client": "workstations-thin-client",
    "server": "servers-physical-server",
    "virtual_machine": "servers-virtual-machine",
    "hypervisor": "servers-hypervisor",
    "printer": "printers-printer",
    "scanner": "printers-scanner",
    "ups": "ups",
    "pdu": "power-pdu",
    "phone": "ip-phones",
    "tv": "tvs",
    "monitor": "monitors",
    "storage": "storage",
}

_SPACE = re.compile(r"\s+")
_LEGAL_SUFFIX = re.compile(r"[.,]?\s*\b(inc|corp|corporation|ltd|llc|co|gmbh|s\.?a)\.?$", re.I)


class RecordError(ValueError):
    """The record cannot be ingested (missing ID/time or wrong shape)."""


def _text(value, limit=150) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, int, float)):
        return None
    text = _SPACE.sub(" ", str(value)).strip()
    return text[:limit] or None


def normalize_manufacturer(value) -> str | None:
    text = _text(value)
    if not text:
        return None
    key = _LEGAL_SUFFIX.sub("", text.lower().replace(",", "")).strip(" .")
    key = _LEGAL_SUFFIX.sub("", key).strip(" .")
    return MANUFACTURER_ALIASES.get(key, MANUFACTURER_ALIASES.get(text.lower(), text))


def normalize_serial(value) -> str | None:
    """Uppercase, trimmed; None for empty, placeholder or single-repeated-character values."""
    text = _text(value, 100)
    if not text:
        return None
    if text.lower() in PLACEHOLDER_SERIALS or len(set(text.replace("-", ""))) <= 1:
        return None
    return text.upper()


def normalize_uuid(value) -> str | None:
    text = _text(value, 64)
    if not text:
        return None
    try:
        parsed = uuid.UUID(text)
    except ValueError:
        return None
    if parsed.int == 0 or parsed.int == (1 << 128) - 1:
        return None
    return str(parsed)


def _mac(value, warnings) -> str | None:
    if not value:
        return None
    try:
        mac = network.normalize_mac(str(value))
    except ValueError:
        warnings.append(f"Ignored invalid MAC address {str(value)[:40]!r}.")
        return None
    if mac in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
        warnings.append(f"Ignored placeholder MAC address {mac}.")
        return None
    return mac


def _ip(value, warnings) -> str | None:
    try:
        return network.normalize_ip(str(value))
    except ValueError:
        warnings.append(f"Ignored invalid IP address {str(value)[:60]!r}.")
        return None


def _hostname(value, warnings) -> str | None:
    if not value:
        return None
    try:
        return network.normalize_hostname(str(value))
    except ValueError:
        warnings.append(f"Ignored invalid hostname {str(value)[:80]!r}.")
        return None


def _observed_at(value) -> str:
    if not isinstance(value, str):
        raise RecordError("observed_at is required (RFC 3339 with offset).")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecordError("observed_at is not a valid timestamp.") from exc
    if parsed.tzinfo is None:
        raise RecordError("observed_at must include a UTC offset.")
    return parsed.isoformat()


def normalize_record(record, *, site_id: str, default_vrf: str = "") -> dict:
    """Return the normalised dict stored on the Observation. Raises RecordError."""
    if not isinstance(record, dict):
        raise RecordError("Each record must be an object.")
    external_id = _text(record.get("external_id"), 200)
    if not external_id:
        raise RecordError("external_id is required.")
    observed_at = _observed_at(record.get("observed_at"))
    warnings: list[str] = []

    hostnames = []
    raw_hosts = record.get("hostnames") or []
    if not isinstance(raw_hosts, list):
        raise RecordError("hostnames must be a list.")
    for value in [record.get("hostname"), record.get("fqdn"), *raw_hosts]:
        host = _hostname(value, warnings)
        if host and host not in hostnames:
            hostnames.append(host)

    interfaces, ip_rows = [], []
    raw_interfaces = record.get("interfaces") or []
    if not isinstance(raw_interfaces, list):
        raise RecordError("interfaces must be a list.")
    for item in raw_interfaces:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"), 64)
        if not name:
            warnings.append("Ignored interface without a name.")
            continue
        try:
            name = network.validate_interface_name(name)
        except ValueError:
            warnings.append(f"Ignored interface with invalid name {name!r}.")
            continue
        interfaces.append({"name": name, "mac": _mac(item.get("mac"), warnings)})
        for address in item.get("ips") or []:
            if ip := _ip(address, warnings):
                ip_rows.append({"address": ip, "interface": name, "vrf": default_vrf})

    raw_ips = record.get("ip_addresses") or []
    if not isinstance(raw_ips, list):
        raise RecordError("ip_addresses must be a list.")
    for item in raw_ips:
        item = item if isinstance(item, dict) else {"address": item}
        if ip := _ip(item.get("address"), warnings):
            row = {
                "address": ip,
                "interface": _text(item.get("interface"), 64),
                "vrf": _text(item.get("vrf"), 64) or default_vrf,
            }
            if not any(r["address"] == ip and r["vrf"] == row["vrf"] for r in ip_rows):
                ip_rows.append(row)
    for row in ip_rows:
        row["site"] = site_id

    serial = normalize_serial(record.get("serial"))
    if record.get("serial") and serial is None:
        warnings.append("Serial number looks like a placeholder; treated as unknown.")
    manufacturer = normalize_manufacturer(record.get("manufacturer"))
    device_type = _text(record.get("device_type"), 40)
    device_type = device_type.lower().replace(" ", "_") if device_type else None

    return {
        "external_id": external_id,
        "observed_at": observed_at,
        "manufacturer": manufacturer,
        "model": _text(record.get("model")),
        "serial_number": serial,
        # Strong identity needs both: a serial is only unique per manufacturer.
        "serial_verified": bool(serial and manufacturer),
        "hardware_uuid": normalize_uuid(record.get("hardware_uuid")),
        "hostnames": hostnames,
        "short_hostnames": sorted({h.split(".")[0] for h in hostnames}),
        "interfaces": interfaces,
        "mac_addresses": sorted({i["mac"] for i in interfaces if i["mac"]}),
        "ip_addresses": ip_rows,
        "os_name": _text(record.get("os_name")),
        "os_version": _text(record.get("os_version"), 100),
        "firmware_version": _text(record.get("firmware_version"), 100),
        "device_type": device_type,
        "category_code": DEVICE_TYPE_TO_CATEGORY.get(device_type or ""),
        "source_version": _text(record.get("source_version"), 100) or "",
        "warnings": warnings,
    }


def checksum(record: dict) -> str:
    """Stable SHA-256 of the raw record, excluding the observation time and any
    top-level key starting with "_" (volatile source metadata such as uptime or poll
    durations, kept in the payload for provenance), so an unchanged device report is
    recognised as unchanged."""
    content = {k: v for k, v in record.items() if k != "observed_at" and not k.startswith("_")}
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
