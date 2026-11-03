"""LibreNMS device → adapter-neutral source record (fixtures/discovery/README.md).

Only facts LibreNMS reports are mapped; anything absent stays unknown. Raw values are
preserved under "raw" (with SNMP credential fields removed) for provenance, and
volatile poller metadata under "_meta", which the checksum ignores.
"""

import ipaddress
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.observations.normalize import normalize_manufacturer

# Never stored: LibreNMS device rows can carry SNMP credentials.
SENSITIVE_KEYS = {
    "community",
    "authname",
    "authpass",
    "authalgo",
    "authlevel",
    "cryptopass",
    "cryptoalgo",
    "snmp_community",
    "password",
    "api_key",
    "token",
}
VOLATILE_KEYS = {
    "uptime",
    "agent_uptime",
    "last_polled",
    "last_poll_attempted",
    "last_polled_timetaken",
    "last_discovered",
    "last_discovered_timetaken",
    "last_ping",
    "last_ping_timetaken",
    "status",
    "status_reason",
}

# LibreNMS OS code → (vendor, OS display name). Unknown codes keep the raw code.
OS_TABLE = {
    "ios": ("Cisco", "Cisco IOS"),
    "iosxe": ("Cisco", "IOS XE"),
    "iosxr": ("Cisco", "IOS XR"),
    "nxos": ("Cisco", "NX-OS"),
    "asa": ("Cisco", "Cisco ASA"),
    "ciscowlc": ("Cisco", "Cisco WLC"),
    "fortigate": ("Fortinet", "FortiOS"),
    "fortios": ("Fortinet", "FortiOS"),
    "fortiswitch": ("Fortinet", "FortiSwitchOS"),
    "procurve": ("HPE Aruba", "ArubaOS-Switch (ProCurve)"),
    "arubaos-cx": ("HPE Aruba", "ArubaOS-CX"),
    "arubaos": ("HPE Aruba", "ArubaOS"),
    "arubainstant": ("HPE Aruba", "Aruba Instant"),
    "comware": ("HPE", "Comware"),
    "vrp": ("Huawei", "Huawei VRP"),
    "gaia": ("Check Point", "Check Point Gaia"),
    "splat": ("Check Point", "Check Point SecurePlatform"),
    "dell-os10": ("Dell", "Dell SmartFabric OS10"),
    "dnos": ("Dell", "Dell Networking OS"),
    "ftos": ("Dell", "Dell Force10 FTOS"),
    "powerconnect": ("Dell", "Dell PowerConnect"),
    "drac": ("Dell", "Dell iDRAC"),
    "junos": ("Juniper", "Junos"),
    "apc": ("APC", "APC AOS"),
    "linux": (None, "Linux"),
    "windows": (None, "Windows"),
}

# sysObjectID enterprise numbers (IANA) → vendor.
ENTERPRISES = {
    "9": "Cisco",
    "12356": "Fortinet",
    "11": "HP",
    "47196": "HPE Aruba",
    "14823": "HPE Aruba",
    "25506": "HPE",
    "2011": "Huawei",
    "2620": "Check Point",
    "674": "Dell",
    "6027": "Dell",
    "2636": "Juniper",
    "318": "APC",
    "8072": None,  # net-snmp: generic, says nothing
}

TYPE_HINTS = {
    "firewall": "firewall",
    "wireless": "access_point",
    "power": "ups",
    "printer": "printer",
    "server": "server",
    "storage": "storage",
    "workstation": "desktop",
}


def _clean(row: dict) -> dict:
    return {k: v for k, v in row.items() if k.lower() not in SENSITIVE_KEYS}


def _text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def vendor_for(device: dict, chassis: dict | None) -> str | None:
    if chassis and _text(chassis.get("entPhysicalMfgName")):
        return normalize_manufacturer(chassis["entPhysicalMfgName"])
    os_code = (device.get("os") or "").lower()
    if os_code in OS_TABLE and OS_TABLE[os_code][0]:
        return OS_TABLE[os_code][0]
    oid = (device.get("sysObjectID") or "").lstrip(".")
    parts = oid.split(".")
    if len(parts) > 6 and parts[:6] == ["1", "3", "6", "1", "4", "1"]:
        return ENTERPRISES.get(parts[6])
    return None


def parse_source_time(value, tz_name: str) -> str | None:
    """LibreNMS timestamps are naive 'YYYY-MM-DD HH:MM:SS' in the LibreNMS server zone."""
    text = _text(value)
    if not text or text.startswith("0000"):
        return None
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        zone = UTC
    try:
        parsed = datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(UTC).isoformat()


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def chassis_rows(inventory: list[dict]) -> list[dict]:
    rows = [r for r in inventory if str(r.get("entPhysicalClass", "")).lower() == "chassis"]
    return sorted(rows, key=lambda r: int(r.get("entPhysicalIndex") or 0))


def device_to_record(
    device: dict,
    *,
    ips: list[dict],
    ports: list[dict],
    inventory: list[dict],
    tz_name: str,
    fetched_at: str,
    enriched_at: str | None,
) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    device = _clean(device)
    chassis = chassis_rows(inventory)
    primary = chassis[0] if chassis else None

    observed_at = parse_source_time(device.get("last_polled"), tz_name)
    if observed_at is None:
        observed_at = fetched_at
        warnings.append("LibreNMS has no last-polled time; using the sync time.")

    serial = _text(device.get("serial")) or (
        _text(primary.get("entPhysicalSerialNum")) if primary else None
    )
    chassis_serial = _text(primary.get("entPhysicalSerialNum")) if primary else None
    if (
        _text(device.get("serial"))
        and chassis_serial
        and chassis_serial != _text(device.get("serial"))
    ):
        warnings.append("Device serial and chassis inventory serial differ; device serial used.")
    model = (_text(primary.get("entPhysicalModelName")) if primary else None) or _text(
        device.get("hardware")
    )

    os_code = (device.get("os") or "").lower()
    os_name = OS_TABLE.get(os_code, (None, os_code or None))[1]

    hostnames = []
    for value in (device.get("hostname"), device.get("sysName")):
        text = _text(value)
        if text and not _is_ip(text) and text not in hostnames:
            hostnames.append(text)

    port_names = {str(p.get("port_id")): p for p in ports}
    interfaces, ip_rows, used_ports = [], [], set()
    for row in ips:
        address = (
            _text(row.get("ipv4_address"))
            or _text(row.get("ipv6_compressed"))
            or _text(row.get("ipv6_address"))
        )
        if not address:
            continue
        port = port_names.get(str(row.get("port_id")))
        name = _text(port.get("ifName")) or _text(port.get("ifDescr")) if port else None
        if port and name and name not in used_ports:
            used_ports.add(name)
            interfaces.append({"name": name, "mac": _text(port.get("ifPhysAddress"))})
        ip_rows.append(
            {"address": address, "vrf": _text(row.get("context_name")) or "", "interface": name}
        )
    management = _text(device.get("ip")) or _text(device.get("hostname"))
    if management and _is_ip(management) and not any(r["address"] == management for r in ip_rows):
        ip_rows.append({"address": management, "vrf": "", "interface": None})

    device_type = TYPE_HINTS.get((device.get("type") or "").lower())
    if os_code in ("fortigate", "fortios", "gaia", "splat", "asa"):
        device_type = "firewall"
    if str(device.get("disabled")) in ("1", "true", "True"):
        warnings.append("Device is disabled in LibreNMS (not polled).")

    stable = {k: v for k, v in device.items() if k not in VOLATILE_KEYS}
    record = {
        "external_id": str(device.get("device_id")),
        "observed_at": observed_at,
        "manufacturer": vendor_for(device, primary),
        "model": model,
        "serial": serial,
        "hostnames": hostnames,
        "interfaces": interfaces,
        "ip_addresses": ip_rows,
        "os_name": os_name,
        "os_version": _text(device.get("version")),
        "firmware_version": _text(primary.get("entPhysicalFirmwareRev")) if primary else None,
        "device_type": device_type,
        "source_version": None,
        "raw": {
            "device": stable,
            "chassis": [_clean(r) for r in chassis],
            "ip": [_clean(r) for r in ips],
            "ports": [
                _clean(p)
                for p in ports
                if (_text(p.get("ifName")) or _text(p.get("ifDescr"))) in used_ports
            ],
        },
        "_meta": {
            "last_polled": device.get("last_polled"),
            "last_discovered": device.get("last_discovered"),
            "status": device.get("status"),
            "uptime": device.get("uptime"),
            "fetched_at": fetched_at,
            "enriched_at": enriched_at,
            "warnings": warnings,
        },
    }
    return record, warnings
