"""LibreNMS adapter: capabilities, connection test, device collection, evidence.

Request budget (docs/05: rate-limit per-device enrichment, FDB at most daily):
- every sync: 1 × GET /devices
- per device, only when new, rediscovered by LibreNMS (last_discovered changed) or the
  cached enrichment is older than enrichment_max_age_hours: GET /devices/{id}/ip,
  GET /devices/{id}/ports (columns-limited), GET /inventory/{id}/all
- evidence pass, every evidence_interval_hours: GET /resources/fdb, GET /resources/links
Optional routes are detected from the API route listing (GET /api/v0) and skipped
when absent.
"""

from collections.abc import Callable
from datetime import datetime, timedelta

from django.db import connection
from django.utils import timezone

from apps.observations.models import Observation

from ..base import AuthError, NotSupported, SourceError
from .client import LibreNMSClient
from .mapping import _clean, device_to_record

# Capability → path fragment expected in the GET /api/v0 route listing.
OPTIONAL_ROUTES = {
    "device_ip": "/ip",
    "device_ports": "/ports",
    "inventory": "inventory",
    "fdb": "resources/fdb",
    "links": "resources/links",
}
PORT_COLUMNS = "port_id,ifName,ifDescr,ifPhysAddress,ifType"
PROGRESS_EVERY = 25


def discover_capabilities(client: LibreNMSClient) -> dict:
    """Which optional routes this LibreNMS version exposes. Unknown → assume absent."""
    try:
        listing = client.get("")
    except NotSupported:
        listing = {}
    urls = " ".join(str(v) for v in listing.values()) if isinstance(listing, dict) else ""
    caps = {"devices": True}
    for name, fragment in OPTIONAL_ROUTES.items():
        caps[name] = fragment in urls
    caps["route_listing"] = bool(urls)
    return caps


def test_connection(client: LibreNMSClient) -> dict:
    system = client.get("/system")
    rows = system.get("system") or []
    info = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    caps = discover_capabilities(client)
    probe = client.get("/devices", params={"type": "all", "limit": 1})
    if "devices" not in probe:
        raise SourceError("GET /devices did not return a device list; check the token's role.")
    return {
        "version": str(info.get("local_ver") or "")[:100],
        "capabilities": caps,
        "requests": client.requests,
    }


class LibreNMSAdapter:
    def __init__(self, instance, client: LibreNMSClient, capabilities: dict | None = None):
        self.instance = instance
        self.client = client
        self.caps = capabilities or instance.capabilities or {}

    def _list(self, path: str, key: str, **params) -> list[dict]:
        body = self.client.get(path, params=params or None)
        rows = body.get(key, []) if isinstance(body, dict) else []
        return [r for r in rows if isinstance(r, dict)]

    def _load_cache(self) -> None:
        """Latest payload per device in one query (PostgreSQL DISTINCT ON); other
        databases fall back to a lookup per device."""
        self._cache: dict[str, dict] | None = None
        if connection.vendor == "postgresql":
            rows = (
                Observation.objects.filter(instance=self.instance)
                .order_by("external_id", "-received_at")
                .distinct("external_id")
                .values_list("external_id", "payload")
            )
            self._cache = {ext: payload for ext, payload in rows}

    def _cached(self, external_id: str) -> dict | None:
        if getattr(self, "_cache", None) is not None:
            payload = self._cache.get(external_id)
            return payload if isinstance(payload, dict) else None
        latest = (
            Observation.objects.filter(instance=self.instance, external_id=external_id)
            .order_by("-received_at")
            .values_list("payload", flat=True)
            .first()
        )
        return latest if isinstance(latest, dict) else None

    def _needs_enrichment(self, device: dict, cached: dict | None, now: datetime) -> bool:
        if cached is None:
            return True
        meta = cached.get("_meta") or {}
        if meta.get("last_discovered") != device.get("last_discovered"):
            return True
        enriched = meta.get("enriched_at")
        if not enriched:
            return True
        try:
            age = now - datetime.fromisoformat(enriched)
        except ValueError:
            return True
        return age > timedelta(hours=self.instance.enrichment_max_age_hours)

    def _enrich(self, device_id: str) -> tuple[list, list, list]:
        ips = (
            self._list(f"/devices/{device_id}/ip", "addresses")
            if self.caps.get("device_ip")
            else []
        )
        ports = []
        if ips and self.caps.get("device_ports"):
            ports = self._list(f"/devices/{device_id}/ports", "ports", columns=PORT_COLUMNS)
        inventory = (
            self._list(f"/inventory/{device_id}/all", "inventory")
            if self.caps.get("inventory")
            else []
        )
        return ips, ports, inventory

    def collect(self, run, progress: Callable[[], None]) -> tuple[list[dict], bool]:
        """Returns (records, complete). Raises AuthError / SourceError when the device
        list itself cannot be read (the run then fails and nothing is marked stale)."""
        run.phase = "devices"
        progress()
        devices = self._list("/devices", "devices", type="all")
        run.devices_total = len(devices)
        run.phase = "enrichment"
        progress()

        now = timezone.now()
        fetched_at = now.isoformat()
        records: list[dict] = []
        self._load_cache()
        self.port_names: dict[str, str] = {}
        for index, device in enumerate(devices, start=1):
            device_id = str(device.get("device_id") or "").strip()
            if not device_id:
                self._warn(run, None, "LibreNMS returned a device without device_id; skipped.")
                continue
            cached = self._cached(device_id)
            raw = (cached or {}).get("raw") or {}
            ips, ports, inventory = raw.get("ip", []), raw.get("ports", []), raw.get("chassis", [])
            enriched_at = ((cached or {}).get("_meta") or {}).get("enriched_at")
            if self._needs_enrichment(device, cached, now):
                try:
                    ips, ports, inventory = self._enrich(device_id)
                    enriched_at = fetched_at
                    run.devices_enriched += 1
                except AuthError:
                    raise
                except SourceError as exc:
                    reused = " Previous enrichment reused." if cached else ""
                    self._warn(run, device_id, f"Enrichment failed: {exc}.{reused}")
            record, warnings = device_to_record(
                device,
                ips=ips,
                ports=ports,
                inventory=inventory,
                tz_name=self.instance.source_timezone,
                fetched_at=fetched_at,
                enriched_at=enriched_at,
            )
            for message in warnings:
                if "disabled" in message or "differ" in message:
                    self._warn(run, device_id, message)
            records.append(record)
            for port in record["raw"]["ports"]:
                name = port.get("ifName") or port.get("ifDescr")
                if port.get("port_id") is not None and name:
                    self.port_names[str(port["port_id"])] = str(name)
            run.devices_processed = index
            run.checkpoint = device_id
            if index % PROGRESS_EVERY == 0:
                progress()
        run.api_requests = self.client.requests
        progress()
        return records, True

    def collect_evidence(self) -> tuple[list[dict], list[dict], list[str]]:
        """FDB and neighbour links. Each list is None-safe; returns (fdb, links, skipped)."""
        skipped: list[str] = []
        fdb = links = []
        if self.caps.get("fdb"):
            fdb = [_clean(r) for r in self._list("/resources/fdb", "ports_fdb")]
        else:
            skipped.append("FDB (route not available on this LibreNMS version)")
        if self.caps.get("links"):
            links = [_clean(r) for r in self._list("/resources/links", "links")]
        else:
            skipped.append("neighbour links (route not available on this LibreNMS version)")
        return fdb, links, skipped

    @staticmethod
    def _warn(run, external_id, message: str) -> None:
        run.warnings += 1
        if len(run.warning_samples) < 20:
            run.warning_samples.append({"external_id": external_id, "warning": message[:300]})
