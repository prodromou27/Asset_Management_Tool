"""Microsoft Intune adapter: Graph v1.0 ``GET /deviceManagement/managedDevices``.

Request budget per sync: one token request (renewed only near expiry or after a 401) and
one GET per page of managed devices, following ``@odata.nextLink``. No per-device reads.

Installed software (Task 016a, ASM-54), only when the integration's "Collect installed
software" switch is on: one GET per page of ``/deviceManagement/detectedApps`` plus one GET
per page of ``/deviceManagement/detectedApps/{id}/managedDevices`` for each app reported on
at least one device. Same permission (DeviceManagementManagedDevices.Read.All). The
software read is complete only when every page succeeded and the device listing was
complete; otherwise software is added or refreshed but nothing is marked removed.

The listing is complete only when the last page has no ``@odata.nextLink``. A page that
fails after the first, a continuation link that fails validation, a repeated link or the
page cap make the listing incomplete: the devices received are processed, but nothing is
marked stale (docs/05 failure behaviour).
"""

from collections.abc import Callable
from urllib.parse import quote

from django.utils import timezone

from ..base import AuthError, SourceError, UnsafeTarget
from .client import REQUIRED_PERMISSION, GraphClient, InvalidQuery
from .mapping import SELECT, device_to_record

COLLECTION = "/deviceManagement/managedDevices"
APPS = "/deviceManagement/detectedApps"
APP_SELECT = "id,displayName,version,publisher,deviceCount"
MAX_PAGES = 2000
MAX_APPS = 20000
PROGRESS_EVERY = 100
# Granted roles whose names mean write or privileged access. The connector never uses
# them; they are reported so the app registration can be reduced to least privilege.
_WRITE_MARKERS = ("readwrite", "privilegedoperations", ".write")


def excess_roles(roles: list[str] | None) -> list[str]:
    return sorted(r for r in roles or [] if any(m in r.lower() for m in _WRITE_MARKERS))


def permission_summary(roles: list[str] | None) -> tuple[dict, str]:
    """(capability flags, warning text) for the roles in the access token."""
    excess = excess_roles(roles)
    caps = {
        "managed_devices": True,
        "detected_apps": True,  # same permission; read only when switched on
        "permission_read_all": roles is None or REQUIRED_PERMISSION in roles,
        "excess_permissions": bool(excess),
    }
    warning = ""
    if excess:
        warning = (
            "The app registration also holds write or privileged permissions "
            f"({', '.join(excess)}). The connector never uses them; remove them so the "
            f"application has only {REQUIRED_PERMISSION}."
        )
    elif roles is not None and REQUIRED_PERMISSION not in roles:
        warning = f"The access token does not list {REQUIRED_PERMISSION}."
    return caps, warning


def test_connection(client: GraphClient) -> dict:
    client.get(COLLECTION, params={"$select": "id", "$top": "1"})
    caps, warning = permission_summary(client.tokens.roles)
    return {
        "version": "Microsoft Graph v1.0",
        "capabilities": caps,
        "requests": client.total_requests,
        "warning": warning,
    }


class IntuneAdapter:
    def __init__(self, instance, client: GraphClient, capabilities: dict | None = None):
        self.instance = instance
        self.client = client
        self.caps = capabilities or instance.capabilities or {}
        # Set only when software is collected (read by store_facts).
        self.software: dict[str, list[dict]] | None = None
        self.software_complete: set[str] = set()

    def prepare(self) -> None:
        """Nothing to detect: Graph v1.0 has one documented route."""

    def _pages(self, run, progress) -> tuple[list[dict], bool]:
        rows: dict[str, dict] = {}
        complete = True
        seen_links: set[str] = set()
        params: dict | None = {"$select": ",".join(SELECT)}
        try:
            body = self.client.get(COLLECTION, params=params)
        except InvalidQuery as exc:
            # Some tenants reject a property in $select; read full objects instead and
            # keep only the selected properties (mapping.PROVENANCE).
            self._warn(run, None, f"Property selection rejected ({exc}); read full objects.")
            body = self.client.get(COLLECTION)
        for page in range(1, MAX_PAGES + 1):
            batch = body.get("value")
            if not isinstance(batch, list):
                if page == 1:
                    raise SourceError("Microsoft Graph returned no device list ('value').")
                self._warn(run, None, f"Page {page} had no device list; listing stopped.")
                complete = False
                break
            for row in batch:
                if not isinstance(row, dict):
                    continue
                external_id = str(row.get("id") or "").strip()
                if not external_id:
                    self._warn(run, None, "A managed device without an ID was skipped.")
                    continue
                if external_id in rows:
                    self._warn(run, external_id, "Listed twice; the first entry was used.")
                    continue
                rows[external_id] = row
            run.checkpoint = f"page {page}"
            run.devices_total = len(rows)
            progress()
            next_link = body.get("@odata.nextLink")
            if not next_link:
                break
            if not isinstance(next_link, str) or next_link in seen_links:
                self._warn(run, None, "Graph repeated a continuation link; listing stopped.")
                complete = False
                break
            seen_links.add(next_link)
            try:
                body = self.client.get_continuation(next_link)
            except AuthError:
                raise
            except UnsafeTarget as exc:
                self._warn(run, None, str(exc))
                complete = False
                break
            except SourceError as exc:
                self._warn(run, None, f"Device list stopped after page {page}: {exc}")
                complete = False
                break
        else:
            self._warn(run, None, f"Stopped after {MAX_PAGES} pages.")
            complete = False
        return list(rows.values()), complete

    def collect(self, run, progress: Callable[[], None]) -> tuple[list[dict], bool]:
        run.phase = "devices"
        progress()
        rows, complete = self._pages(run, progress)
        _, warning = permission_summary(self.client.tokens.roles)
        if warning:
            self._warn(run, None, warning)

        fetched_at = timezone.now().isoformat()
        records = []
        for index, row in enumerate(rows, start=1):
            record, warnings = device_to_record(
                row, tenant_id=self.instance.tenant_id, fetched_at=fetched_at
            )
            for message in warnings:
                self._warn(run, record["external_id"], message)
            records.append(record)
            run.devices_processed = index
            if index % PROGRESS_EVERY == 0:
                progress()
        if self.instance.collect_software:
            self._detected_apps(run, progress, {r["external_id"] for r in records}, complete)
        run.api_requests = self.client.total_requests
        progress()
        return records, complete

    # --- Detected apps ----------------------------------------------------------------

    def _collection(self, run, path: str, params: dict | None, what: str) -> tuple[list, bool]:
        """Every page of a Graph collection; (rows, complete)."""
        rows: list = []
        seen: set[str] = set()
        try:
            body = self.client.get(path, params=params)
        except AuthError:
            raise
        except SourceError as exc:
            self._warn(run, None, f"{what} not read: {exc}")
            return rows, False
        for _ in range(MAX_PAGES):
            batch = body.get("value") if isinstance(body, dict) else None
            if not isinstance(batch, list):
                self._warn(run, None, f"{what}: unexpected response; stopped.")
                return rows, False
            rows.extend(r for r in batch if isinstance(r, dict))
            next_link = body.get("@odata.nextLink")
            if not next_link:
                return rows, True
            if not isinstance(next_link, str) or next_link in seen:
                self._warn(run, None, f"{what}: repeated continuation link; stopped.")
                return rows, False
            seen.add(next_link)
            try:
                body = self.client.get_continuation(next_link)
            except AuthError:
                raise
            except SourceError as exc:
                self._warn(run, None, f"{what} stopped: {exc}")
                return rows, False
        self._warn(run, None, f"{what}: stopped after {MAX_PAGES} pages.")
        return rows, False

    def _detected_apps(self, run, progress, device_ids: set[str], listing_complete: bool) -> None:
        run.phase = "software"
        progress()
        apps, complete = self._collection(run, APPS, {"$select": APP_SELECT}, "Detected apps")
        if len(apps) > MAX_APPS:
            self._warn(
                run, None, f"{len(apps)} detected apps; only the first {MAX_APPS} were read."
            )
            apps, complete = apps[:MAX_APPS], False
        software: dict[str, list[dict]] = {d: [] for d in device_ids}
        for index, app in enumerate(apps, start=1):
            app_id = str(app.get("id") or "").strip()
            name = str(app.get("displayName") or "").strip()
            if not app_id or not name:
                continue
            count = app.get("deviceCount")
            if isinstance(count, int) and count <= 0:
                continue
            devices, ok = self._collection(
                run,
                f"{APPS}/{quote(app_id, safe='')}/managedDevices",
                {"$select": "id"},
                f"Devices of {name[:80]}",
            )
            complete = complete and ok
            item = {
                "name": name,
                "publisher": str(app.get("publisher") or ""),
                "version": str(app.get("version") or ""),
                "source_ref": app_id,
            }
            for device in devices:
                device_id = str(device.get("id") or "").strip()
                if device_id in software:
                    software[device_id].append(item)
            if index % PROGRESS_EVERY == 0:
                run.checkpoint = f"apps {index}/{len(apps)}"
                progress()
        self.software = software
        self.software_complete = set(software) if complete and listing_complete else set()

    @staticmethod
    def _warn(run, external_id, message: str) -> None:
        run.warnings += 1
        if len(run.warning_samples) < 20:
            run.warning_samples.append({"external_id": external_id, "warning": message[:300]})
