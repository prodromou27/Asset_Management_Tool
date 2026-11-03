"""Endpoint Central computer → adapter-neutral source record.

Response shapes differ between Endpoint Central builds and API generations, so every
field is looked up under a short list of documented/observed key names (case- and
separator-insensitive) anywhere in the computer's detail document. Field names are
fixture-derived and must be confirmed against the installed build (docs/17 ASM-29).
Only values the source reports are mapped; everything else stays unknown. The exact
source keys and values used are kept under "raw" for provenance; volatile values (agent
contact time, live status, free space) are not, so unchanged computers keep the same
checksum.
"""

import ipaddress
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SENSITIVE_WORDS = ("password", "passwd", "secret", "token", "apikey", "api_key", "credential")

FIELDS = {
    "external_id": ("resource_id", "resourceid", "res_id", "computer_id", "id"),
    "name": ("resource_name", "computer_name", "name", "hostname", "host_name"),
    "fqdn": ("fqdn_name", "fqdn", "dns_name", "full_name"),
    "domain": ("domain_netbios_name", "domain_name", "domain"),
    "manufacturer": (
        "device_manufacturer",
        "system_manufacturer",
        "computer_manufacturer",
        "manufacturer",
        "bios_manufacturer_name_of_system",
        "vendor",
    ),
    "model": ("device_model", "system_model", "computer_model", "model", "product_name"),
    "serial": (
        "serial_number",
        "serialnumber",
        "device_serial_number",
        "system_serial_number",
        "service_tag",
        "bios_serial_number",
    ),
    "hardware_uuid": ("system_uuid", "smbios_uuid", "hardware_uuid"),
    "os_name": ("os_name", "operating_system", "os"),
    "os_version": ("os_version", "os_version_number"),
    "os_build": ("build_number", "os_build_number", "build"),
    "chassis": ("chassis_type", "device_type", "computer_type", "form_factor", "system_type"),
    "observed": (
        "last_successful_scan",
        "last_scan_time",
        "lastsuccessfulscan",
        "last_successful_scan_time",
    ),
    "contact": ("agent_last_contact_time", "last_contact_time", "agent_last_contact"),
    "agent_version": ("agent_version",),
    "ip": ("ip_address", "ipaddress"),
    "mac": ("mac_address", "macaddress"),
}
ADAPTER_NAME = ("adapter_name", "name", "description", "adapter_description", "nic_name")
ADAPTER_MAC = ("mac_address", "macaddress", "physical_address")
ADAPTER_IP = ("ip_address", "ipaddress", "ip_addresses", "ipv4_address")

LAPTOP = ("laptop", "notebook", "portable", "convertible", "detachable", "tablet", "sub notebook")
DESKTOP = (
    "desktop",
    "tower",
    "all in one",
    "all-in-one",
    "low profile",
    "mini pc",
    "small form factor",
    "space-saving",
    "space saving",
    "lunch box",
    "pizza box",
    "sealed-case",
    "stick pc",
)
# SMBIOS/OEM defaults that mean "not filled in"; treated as unknown.
PLACEHOLDERS = {
    "to be filled by o.e.m.",
    "to be filled by oem",
    "system manufacturer",
    "system product name",
    "default string",
    "o.e.m.",
    "oem",
    "not applicable",
    "not specified",
    "none",
    "unknown",
}
VIRTUAL = ("vmware", "virtualbox", "virtual machine", "kvm", "qemu", "hyper-v", "xen")


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _scalar(value) -> bool:
    return isinstance(value, str | int | float) and not isinstance(value, bool)


def _walk(doc, depth=0):
    """Yield (key, value) for scalars in nested dicts (not inside lists)."""
    if depth > 4 or not isinstance(doc, dict):
        return
    for key, value in doc.items():
        if isinstance(value, dict):
            yield from _walk(value, depth + 1)
        elif _scalar(value):
            yield key, value


def pick(docs: list, names: tuple[str, ...]) -> tuple[str | None, str | None]:
    """First non-empty value for any of `names` (in priority order) across `docs`."""
    wanted = [_key(n) for n in names]
    index: dict[str, tuple[str, str]] = {}
    for doc in docs:
        for key, value in _walk(doc):
            text = str(value).strip()
            if text and text.lower() not in ("--", "-", "n/a", "na", "null", "none", "unknown"):
                index.setdefault(_key(key), (key, text))
    for name in wanted:
        if name in index:
            return index[name]
    return None, None


def find_rows(doc, wanted: tuple[str, ...], depth=0) -> list[dict]:
    """A list of dicts whose items carry any of `wanted` keys, anywhere in `doc`."""
    keys = {_key(k) for k in wanted}
    if depth > 5:
        return []
    if isinstance(doc, list):
        rows = [r for r in doc if isinstance(r, dict)]
        if rows and any(keys & {_key(k) for k in r} for r in rows):
            return rows
        for item in doc:
            found = find_rows(item, wanted, depth + 1)
            if found:
                return found
    elif isinstance(doc, dict):
        for value in doc.values():
            found = find_rows(value, wanted, depth + 1)
            if found:
                return found
    return []


def parse_time(value, tz_name: str) -> str | None:
    """Epoch milliseconds/seconds, ISO 8601, or naive 'YYYY-MM-DD HH:MM:SS' in tz_name."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if re.fullmatch(r"-?\d{9,14}", text):
        number = int(text)
        if number <= 0:
            return None
        seconds = number / 1000 if number > 10**11 else number
        return datetime.fromtimestamp(seconds, tz=UTC).isoformat()
    try:
        parsed = datetime.fromisoformat(text.replace(" ", "T", 1))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(tz_name))
        except ZoneInfoNotFoundError:
            parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _split_ips(value) -> list[str]:
    if isinstance(value, list):
        parts = [str(v) for v in value]
    else:
        parts = re.split(r"[,;\s]+", str(value or ""))
    out = []
    for part in parts:
        part = part.strip()
        try:
            address = ipaddress.ip_address(part)
        except ValueError:
            continue
        if not (address.is_loopback or address.is_link_local or address.is_unspecified):
            out.append(part)
    return out


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


ADAPTER_KEYS = {_key(k) for k in (*ADAPTER_NAME, *ADAPTER_MAC, *ADAPTER_IP)}


def _identity(adapter: dict) -> dict:
    """Only the identifying adapter values (no lease times, speeds or counters)."""
    return {
        k: v
        for k, v in adapter.items()
        if _key(k) in ADAPTER_KEYS and not any(w in _key(k) for w in map(_key, SENSITIVE_WORDS))
    }


def device_type(chassis: str | None, os_name: str | None, maker: str | None, model: str | None):
    text = (chassis or "").lower()
    machine = f"{maker or ''} {model or ''}".lower()
    if any(word in machine for word in VIRTUAL):
        return "virtual_machine"
    if "server" in (os_name or "").lower() or "server" in text:
        return "server"
    if any(word in text for word in LAPTOP):
        return "laptop"
    if any(word in text for word in DESKTOP):
        return "desktop"
    return None


def computer_to_record(
    row: dict, details: list[dict], *, tz_name: str, fetched_at: str, enriched_at: str | None
) -> tuple[dict, list[str]]:
    """`row` is the computer list entry; `details` the per-computer documents (may be [])."""
    warnings: list[str] = []
    docs = [row, *details]
    used: dict[str, str] = {}

    def value(field: str) -> str | None:
        key, found = pick(docs, FIELDS[field])
        if key is not None:
            used[key] = found
        return found

    external_id = value("external_id")
    observed = parse_time(pick([row, *details], FIELDS["observed"])[1], tz_name)
    contact = parse_time(pick(docs, FIELDS["contact"])[1], tz_name)
    observed_at = observed or contact
    if observed_at is None:
        observed_at = fetched_at
        warnings.append("No inventory scan time reported; using the sync time.")
    elif observed is None:
        warnings.append("No successful inventory scan reported; using the last agent contact.")

    hostnames = []
    for field in ("fqdn", "name"):
        text = value(field)
        if text and not _is_ip(text) and text not in hostnames:
            hostnames.append(text)

    maker, model = value("manufacturer"), value("model")
    for label, text in (("manufacturer", maker), ("model", model)):
        if text and text.strip().lower() in PLACEHOLDERS:
            warnings.append(f"The {label} is a placeholder ({text!r}); treated as unknown.")
    maker = None if maker and maker.strip().lower() in PLACEHOLDERS else maker
    model = None if model and model.strip().lower() in PLACEHOLDERS else model
    os_name, os_version, build = value("os_name"), value("os_version"), value("os_build")
    if os_version and build and build not in os_version:
        os_version = f"{os_version} (build {build})"
    elif not os_version and build:
        os_version = build
    chassis = value("chassis")

    interfaces, seen_macs = [], set()
    adapters = []
    for doc in details:
        adapters = find_rows(doc, ADAPTER_MAC)
        if adapters:
            break
    for adapter in adapters:
        _, mac = pick([adapter], ADAPTER_MAC)
        _, name = pick([adapter], ADAPTER_NAME)
        ip_keys = {_key(k) for k in ADAPTER_IP}
        ips: list[str] = []
        for k, v in adapter.items():
            if _key(k) in ip_keys and v:
                ips.extend(ip for ip in _split_ips(v) if ip not in ips)
        if not mac and not ips:
            continue
        if mac and mac.lower() in seen_macs:
            continue
        seen_macs.add((mac or "").lower())
        interfaces.append({"name": name or "Network adapter", "mac": mac, "ips": ips})
    if not interfaces:  # fall back to the summary row's single address
        mac, ips = value("mac"), _split_ips(value("ip") or "")
        if mac or ips:
            interfaces.append({"name": "Primary adapter", "mac": mac, "ips": ips})

    record = {
        "external_id": external_id,
        "observed_at": observed_at,
        "manufacturer": maker,
        "model": model,
        "serial": value("serial"),
        "hardware_uuid": value("hardware_uuid"),
        "hostnames": hostnames,
        "interfaces": interfaces,
        "os_name": os_name,
        "os_version": os_version,
        "device_type": device_type(chassis, os_name, maker, model),
        "source_version": value("agent_version"),
        "raw": {
            "fields": dict(sorted(used.items())),
            "network_adapters": [_identity(a) for a in adapters],
        },
        "_meta": {
            "last_successful_scan": observed,
            "agent_last_contact": contact,
            "domain": pick(docs, FIELDS["domain"])[1],  # descriptive; not in the checksum
            "fetched_at": fetched_at,
            "enriched_at": enriched_at,
            "warnings": warnings,
        },
    }
    return record, warnings
