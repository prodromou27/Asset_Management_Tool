"""Intune managedDevice (Graph v1.0) → adapter-neutral source record.

Only documented v1.0 managedDevice properties are read (``SELECT``). The values used are
kept under ``raw.fields`` exactly as Graph returned them, together with the tenant, for
provenance. Personal data that ITAM does not need for identity (user principal name,
e-mail, phone number, IMEI and similar) is neither selected nor stored. Volatile values
(the last Intune check-in time) live under ``_meta`` so an unchanged device keeps the same
checksum; a change in compliance, enrollment or management state is a real change and
creates a new observation.
"""

import re
from datetime import UTC, datetime

from apps.assets import network

# Documented Graph v1.0 managedDevice properties used by the connector.
SELECT = (
    "id",
    "deviceName",
    "manufacturer",
    "model",
    "serialNumber",
    "operatingSystem",
    "osVersion",
    "azureADDeviceId",
    "deviceRegistrationState",
    "deviceEnrollmentType",
    "enrolledDateTime",
    "lastSyncDateTime",
    "complianceState",
    "managementAgent",
    "managedDeviceOwnerType",
    "wiFiMacAddress",
)
# Stored as provenance (everything selected except the volatile check-in time).
PROVENANCE = tuple(k for k in SELECT if k != "lastSyncDateTime")

# Graph returns this for "never" in DateTimeOffset properties.
_NEVER = "0001-01-01"
_ZERO_GUID = "00000000-0000-0000-0000-000000000000"
_FRACTION = re.compile(r"(\.\d+)")
PLACEHOLDERS = {
    "",
    "unknown",
    "to be filled by o.e.m.",
    "system manufacturer",
    "system product name",
    "default string",
}

VIRTUAL_MODELS = ("virtual machine", "vmware", "virtualbox", "kvm", "qemu", "parallels")
# Product lines whose form factor is unambiguous. Anything else is left to the reviewer.
LAPTOP_MODELS = (
    "macbook",
    "latitude",
    "thinkpad",
    "elitebook",
    "probook",
    "zbook",
    "surface laptop",
    "surface book",
)
DESKTOP_MODELS = ("imac", "mac mini", "mac studio", "mac pro", "optiplex", "elitedesk", "prodesk")


def _text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_time(value) -> str | None:
    """Graph DateTimeOffset (ISO 8601, usually 'Z') → ISO string with offset, or None."""
    text = _text(value)
    if not text or text.startswith(_NEVER):
        return None
    # Graph may send 7 fractional digits (.NET ticks); Python accepts at most 6.
    text = _FRACTION.sub(lambda m: m.group(1)[:7], text)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)  # Graph times are UTC
    return parsed.isoformat()


def device_type(os_name: str | None, maker: str | None, model: str | None) -> str | None:
    machine = f"{maker or ''} {model or ''}".lower()
    if any(word in machine for word in VIRTUAL_MODELS):
        return "virtual_machine"
    if "server" in (os_name or "").lower():
        return "server"
    text = (model or "").lower()
    if any(f" {word}" in f" {text}" for word in LAPTOP_MODELS):
        return "laptop"
    if any(f" {word}" in f" {text}" for word in DESKTOP_MODELS):
        return "desktop"
    return None  # phones, tablets and unknown form factors: the reviewer decides


def _hostname(name: str | None) -> str | None:
    """Intune deviceName is the computer name on Windows/macOS but a free label on
    phones ("Alex's iPhone"); only valid host names are used as hostnames."""
    if not name:
        return None
    try:
        return network.normalize_hostname(name)
    except ValueError:
        return None


def device_to_record(row: dict, *, tenant_id: str, fetched_at: str) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    get = {k.lower(): v for k, v in row.items()}.get  # tolerate key-case drift

    external_id = _text(get("id"))
    last_sync = parse_time(get("lastsyncdatetime"))
    enrolled = parse_time(get("enrolleddatetime"))
    observed_at = last_sync or enrolled
    if observed_at is None:
        observed_at = fetched_at
        warnings.append("Intune reports no check-in or enrollment time; using the sync time.")
    elif last_sync is None:
        warnings.append("The device has not checked in with Intune; using the enrollment time.")

    maker, model = _text(get("manufacturer")), _text(get("model"))
    for label, text in (("manufacturer", maker), ("model", model)):
        if text and text.lower() in PLACEHOLDERS:
            warnings.append(f"The {label} is a placeholder ({text!r}); treated as unknown.")
    maker = None if maker and maker.lower() in PLACEHOLDERS else maker
    model = None if model and model.lower() in PLACEHOLDERS else model
    os_name, os_version = _text(get("operatingsystem")), _text(get("osversion"))

    name = _text(get("devicename"))
    hostname = _hostname(name)
    mac = _text(get("wifimacaddress"))
    interfaces = []
    if mac:
        if re.fullmatch(r"[0-9A-Fa-f:.\-]{12,17}", mac) and set(re.sub(r"\W", "", mac)) != {"0"}:
            interfaces.append({"name": "Wi-Fi", "mac": mac})
        else:
            warnings.append(f"Ignored invalid Wi-Fi MAC address {mac[:40]!r}.")

    entra_id = _text(get("azureaddeviceid"))
    if entra_id == _ZERO_GUID:
        entra_id = None

    fields = {}
    for key in PROVENANCE:
        value = get(key.lower())
        if value is not None and value != "":
            fields[key] = value

    record = {
        "external_id": external_id,
        "observed_at": observed_at,
        "manufacturer": maker,
        "model": model,
        "serial": _text(get("serialnumber")),
        "hostname": hostname,
        "interfaces": interfaces,
        "os_name": os_name,
        "os_version": os_version,
        "device_type": device_type(os_name, maker, model),
        "raw": {
            "tenant_id": tenant_id,
            "managed_device_id": external_id,
            "entra_device_id": entra_id,
            "fields": dict(sorted(fields.items())),
        },
        "_meta": {
            "last_sync": last_sync,
            "fetched_at": fetched_at,
            "warnings": warnings,
        },
    }
    return record, warnings
