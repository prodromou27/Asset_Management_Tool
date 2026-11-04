"""Endpoint Central (on-premises) adapter: API generation handshake, paginated computer
list, cached per-computer detail reads.

docs/05: select the route family only after a real handshake. The connection test (and
the first sync, if no test ran) probes the current ``/dcapi`` inventory route, then the
older ``/api/1.4`` route, with ``GET`` and a page size of 1, and keeps the first one
whose response contains a recognisable computer list.

Request budget per sync: the computer list (page size 500), plus per computer, only when
it is new, Endpoint Central reports a newer successful inventory scan, or the cached
details are older than ``enrichment_max_age_hours``: 1 request (api/1.4
compdetailssummary) or up to 4 (dcapi summary, hardware, osInformation, network).

Installed software (Task 016a, ASM-54) is read only when the integration's "Collect
installed software" switch is on and the dcapi generation is in use: one extra
``GET /dcapi/inventory/computers/{id}/softwareInfo`` per computer whose details are
refreshed in this sync, plus once for computers with no software recorded yet. Other
computers keep their previously stored software.
"""

from collections.abc import Callable
from datetime import datetime, timedelta

from django.db import connection
from django.utils import timezone

from apps.observations.models import Observation

from ..base import AuthError, NotSupported, SourceError
from .client import EndpointCentralClient
from .mapping import FIELDS, SOFTWARE_FIELDS, computer_to_record, find_rows, parse_time, pick

PAGE_SIZE = 500
MAX_PAGES = 1000
PROGRESS_EVERY = 25

FAMILIES = {
    "dcapi": {
        "list": "/dcapi/inventory/viewData/scanComputers",
        "page": ("page", "pageLimit"),
        "details": (
            "/dcapi/inventory/computers/{id}/summary",
            "/dcapi/inventory/computers/{id}/hardware",
            "/dcapi/inventory/computers/{id}/osInformation",
            "/dcapi/inventory/computers/{id}/network",
        ),
        "detail_param": None,
        "software": "/dcapi/inventory/computers/{id}/softwareInfo",
    },
    "api_1_4": {
        "list": "/api/1.4/inventory/scancomputers",
        "page": ("page", "pagelimit"),
        "details": ("/api/1.4/inventory/compdetailssummary",),
        "detail_param": "resid",
        "software": None,
    },
}
ORDER = ("dcapi", "api_1_4")
SERVER_INFO = "/api/1.4/desktop/serverproperties"
VERSION_KEYS = (
    "build_number",
    "server_build_number",
    "product_version",
    "server_version",
    "version",
)


def family_of(caps: dict) -> str | None:
    return next((f for f in ORDER if caps.get(f"route_{f}")), None)


def computer_rows(body) -> list[dict]:
    return find_rows(body, FIELDS["external_id"])


def _total(body) -> int | None:
    _, value = pick([body], ("total", "total_count", "totalcount", "total_records", "count"))
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def detect_family(client: EndpointCentralClient) -> tuple[str | None, str]:
    """(family, note). Tries each generation's list route with one row."""
    notes = []
    for family in ORDER:
        spec = FAMILIES[family]
        page, limit = spec["page"]
        try:
            body = client.get(spec["list"], params={page: 1, limit: 1})
        except NotSupported:
            notes.append(f"{family}: route not available")
            continue
        if computer_rows(body) or _total(body) == 0:
            return family, f"Using the {family} inventory API."
        notes.append(f"{family}: response format not recognised")
    return None, "; ".join(notes)


def test_connection(client: EndpointCentralClient) -> dict:
    family, note = detect_family(client)
    if family is None:
        raise SourceError(
            "No supported Endpoint Central inventory API was found "
            f"({note}). Capture a sanitized sample for review (DEC-06)."
        )
    version = ""
    try:
        info = client.get(SERVER_INFO)
        version = str(pick([info], VERSION_KEYS)[1] or "")[:100]
    except NotSupported:
        pass
    except AuthError:
        raise
    except SourceError:
        pass  # version is informational only
    caps = {"computers": True, "computer_details": True, "software": family == "dcapi"}
    caps.update({f"route_{f}": f == family for f in ORDER})
    return {"version": version, "capabilities": caps, "requests": client.requests, "note": note}


class EndpointCentralAdapter:
    def __init__(self, instance, client: EndpointCentralClient, capabilities: dict | None = None):
        self.instance = instance
        self.client = client
        self.caps = capabilities or instance.capabilities or {}
        self.missing_details: set[str] = set()
        # Set only when software is collected (read by store_facts).
        self.software: dict[str, list[dict]] | None = None
        self.software_complete: set[str] = set()

    def prepare(self) -> None:
        if family_of(self.caps):
            return
        from apps.integrations.models import IntegrationInstance

        family, note = detect_family(self.client)
        if family is None:
            raise SourceError(f"No supported Endpoint Central inventory API was found ({note}).")
        self.caps = {"computers": True, "computer_details": True, "software": family == "dcapi"}
        self.caps.update({f"route_{f}": f == family for f in ORDER})
        IntegrationInstance.objects.filter(pk=self.instance.pk).update(capabilities=self.caps)

    # --- Listing -----------------------------------------------------------------------

    def _list(self, run, progress) -> tuple[list[dict], bool]:
        spec = FAMILIES[family_of(self.caps)]
        page_key, limit_key = spec["page"]
        rows: dict[str, dict] = {}
        total = None
        complete = True
        previous_first = None
        for page in range(1, MAX_PAGES + 1):
            try:
                body = self.client.get(spec["list"], params={page_key: page, limit_key: PAGE_SIZE})
            except AuthError:
                raise
            except SourceError as exc:
                if page == 1:
                    raise
                self._warn(run, None, f"Computer list stopped at page {page}: {exc}")
                complete = False
                break
            batch = computer_rows(body)
            total = _total(body) if total is None else total
            first = pick([batch[0]], FIELDS["external_id"])[1] if batch else None
            if batch and first == previous_first:
                self._warn(run, None, f"Page {page} repeated the previous page; listing stopped.")
                complete = False
                break
            previous_first = first
            for row in batch:
                external_id = pick([row], FIELDS["external_id"])[1]
                if not external_id:
                    self._warn(run, None, "A computer without a resource ID was skipped.")
                    continue
                if external_id in rows:
                    self._warn(run, external_id, "Listed twice; the first entry was used.")
                    continue
                rows[external_id] = row
            run.checkpoint = f"page {page}"
            run.devices_total = max(total or 0, len(rows))
            progress()
            if len(batch) < PAGE_SIZE or (total is not None and len(rows) >= total):
                break
        else:
            self._warn(run, None, f"Stopped after {MAX_PAGES} pages.")
            complete = False
        if complete and total is not None and len(rows) < total:
            self._warn(run, None, f"Listed {len(rows)} of {total} computers reported.")
            complete = False
        return list(rows.values()), complete

    # --- Details -----------------------------------------------------------------------

    def _load_cache(self) -> None:
        self._cache: dict[str, dict] | None = None
        if connection.vendor == "postgresql":
            rows = (
                Observation.objects.filter(instance=self.instance)
                .order_by("external_id", "-received_at")
                .distinct("external_id")
                .values_list("external_id", "payload")
            )
            self._cache = dict(rows)

    def _cached(self, external_id: str) -> dict | None:
        if self._cache is not None:
            payload = self._cache.get(external_id)
        else:
            payload = (
                Observation.objects.filter(instance=self.instance, external_id=external_id)
                .order_by("-received_at")
                .values_list("payload", flat=True)
                .first()
            )
        return payload if isinstance(payload, dict) else None

    def _needs_details(self, row: dict, cached: dict | None, now: datetime) -> bool:
        if cached is None:
            return True
        meta = cached.get("_meta") or {}
        scan = parse_time(pick([row], FIELDS["observed"])[1], self.instance.source_timezone)
        if scan and scan != meta.get("last_successful_scan"):
            return True
        try:
            age = now - datetime.fromisoformat(meta.get("enriched_at") or "")
        except ValueError:
            return True
        return age > timedelta(hours=self.instance.enrichment_max_age_hours)

    def _details(self, external_id: str) -> list[dict]:
        spec = FAMILIES[family_of(self.caps)]
        docs = []
        for template in spec["details"]:
            if template in self.missing_details:
                continue
            if spec["detail_param"]:
                path, params = template, {spec["detail_param"]: external_id}
            else:
                path, params = template.format(id=external_id), None
            try:
                docs.append(self.client.get(path, params=params))
            except NotSupported:
                self.missing_details.add(template)
        return docs

    @staticmethod
    def _cached_docs(cached: dict | None) -> list[dict]:
        raw = (cached or {}).get("raw") or {}
        docs = [dict(raw.get("fields") or {})]
        if raw.get("network_adapters"):
            docs.append({"network_adapters": raw["network_adapters"]})
        return docs

    def _software(self, external_id: str) -> list[dict]:
        path = FAMILIES[family_of(self.caps)]["software"].format(id=external_id)
        body = self.client.get(path)
        items = []
        for row in find_rows(body, SOFTWARE_FIELDS["name"]):
            name = pick([row], SOFTWARE_FIELDS["name"])[1]
            if not name:
                continue
            installed = parse_time(pick([row], SOFTWARE_FIELDS["installed"])[1], "UTC")
            items.append(
                {
                    "name": name,
                    "publisher": pick([row], SOFTWARE_FIELDS["publisher"])[1] or "",
                    "version": pick([row], SOFTWARE_FIELDS["version"])[1] or "",
                    "source_ref": pick([row], SOFTWARE_FIELDS["source_ref"])[1] or "",
                    "installed_on": installed[:10] if installed else None,
                }
            )
        return items

    def _software_wanted(self, run) -> set[str] | None:
        """External IDs that already have software stored, or None when not collecting."""
        if not self.instance.collect_software:
            return None
        if not FAMILIES[family_of(self.caps)]["software"]:
            self._warn(
                run, None, "Installed software needs the dcapi API generation; not collected."
            )
            return None
        from apps.software.models import SoftwareInstallation

        self.software = {}
        return set(
            SoftwareInstallation.objects.filter(instance=self.instance)
            .values_list("external_id", flat=True)
            .distinct()
        )

    def collect(self, run, progress: Callable[[], None]) -> tuple[list[dict], bool]:
        run.phase = "devices"
        progress()
        rows, complete = self._list(run, progress)
        run.devices_total = len(rows)
        run.phase = "enrichment"
        progress()

        now = timezone.now()
        fetched_at = now.isoformat()
        tz_name = self.instance.source_timezone
        self._load_cache()
        known_software = self._software_wanted(run)
        records = []
        for index, row in enumerate(rows, start=1):
            external_id = pick([row], FIELDS["external_id"])[1]
            cached = self._cached(external_id)
            details = self._cached_docs(cached) if cached else []
            enriched_at = ((cached or {}).get("_meta") or {}).get("enriched_at")
            if self._needs_details(row, cached, now):
                try:
                    details = self._details(external_id)
                    enriched_at = fetched_at
                    run.devices_enriched += 1
                except AuthError:
                    raise
                except SourceError as exc:
                    reused = " Previous details reused." if cached else ""
                    self._warn(run, external_id, f"Details not read: {exc}.{reused}")
            refreshed = enriched_at == fetched_at
            if known_software is not None and (refreshed or external_id not in known_software):
                try:
                    self.software[external_id] = self._software(external_id)
                    self.software_complete.add(external_id)
                except AuthError:
                    raise
                except NotSupported:
                    self._warn(run, external_id, "Installed software route not available.")
                except SourceError as exc:
                    self._warn(run, external_id, f"Installed software not read: {exc}.")
            record, warnings = computer_to_record(
                row, details, tz_name=tz_name, fetched_at=fetched_at, enriched_at=enriched_at
            )
            for message in warnings:
                self._warn(run, external_id, message)
            records.append(record)
            run.devices_processed = index
            if index % PROGRESS_EVERY == 0:
                progress()
        for template in sorted(self.missing_details):
            self._warn(run, None, f"Not collected: {template} (route not available).")
        run.api_requests = self.client.requests
        progress()
        return records, complete

    @staticmethod
    def _warn(run, external_id, message: str) -> None:
        run.warnings += 1
        if len(run.warning_samples) < 20:
            run.warning_samples.append({"external_id": external_id, "warning": message[:300]})
