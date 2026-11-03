"""Microsoft Defender for Endpoint adapter: ``GET /api/machines`` only.

Pagination uses the documented OData options: ``$top`` (page size, at most 10,000; 1,000
here) with ``@odata.nextLink`` when the API returns one, otherwise ``$skip``. Full runs
list every machine; incremental runs add ``$filter=lastSeen gt <last success - 1 h>`` and
never mark anything stale. The listing is incomplete (nothing is marked stale or missing)
when a later page fails, a continuation link is unsafe or repeated, the hourly request
budget runs out, or the page cap is reached.

Security facts go to ``apps.security`` through ``store_security_states`` after
reconciliation; they never update asset fields.
"""

from collections.abc import Callable
from datetime import UTC, timedelta

from django.db import transaction
from django.utils import timezone

from ..base import AuthError, SourceError, UnsafeTarget
from .client import REQUIRED_PERMISSION, BudgetExhausted, DefenderClient
from .mapping import machine_to_record, security_state

COLLECTION = "/machines"
PAGE_SIZE = 1000
MAX_PAGES = 1000
PROGRESS_EVERY = 100
INCREMENTAL_OVERLAP = timedelta(hours=1)


def excess_roles(roles: list[str] | None) -> list[str]:
    """Device-action or write roles (Machine.Isolate, Machine.Scan, ... , *.ReadWrite.*)."""
    out = []
    for role in roles or []:
        lowered = role.lower()
        if role == REQUIRED_PERMISSION:
            continue
        if lowered.startswith("machine.") or "readwrite" in lowered or ".write" in lowered:
            out.append(role)
    return sorted(out)


def permission_summary(roles: list[str] | None) -> tuple[dict, str]:
    excess = excess_roles(roles)
    caps = {
        "machines": True,
        "advanced_hunting": False,
        "device_actions": False,
        "permission_read_all": roles is None or REQUIRED_PERMISSION in roles,
        "excess_permissions": bool(excess),
    }
    warning = ""
    if excess:
        warning = (
            "The app registration also holds device-action or write permissions "
            f"({', '.join(excess)}). The connector never uses them; remove them so the "
            f"application has only {REQUIRED_PERMISSION}."
        )
    elif roles is not None and REQUIRED_PERMISSION not in roles:
        warning = f"The access token does not list {REQUIRED_PERMISSION}."
    return caps, warning


def test_connection(client: DefenderClient) -> dict:
    client.get(COLLECTION, params={"$top": "1"})
    caps, warning = permission_summary(client.tokens.roles)
    return {
        "version": "Defender for Endpoint API",
        "capabilities": caps,
        "requests": client.total_requests,
        "warning": warning,
    }


class DefenderAdapter:
    def __init__(self, instance, client: DefenderClient, capabilities: dict | None = None):
        self.instance = instance
        self.client = client
        self.caps = capabilities or instance.capabilities or {}

    def prepare(self) -> None:
        """Nothing to detect: one documented route."""

    def _base_params(self, run) -> dict:
        params = {"$top": str(PAGE_SIZE)}
        since = self.instance.last_success_at
        if run.mode == "incremental" and since is not None:
            cutoff = (since - INCREMENTAL_OVERLAP).astimezone(UTC)
            params["$filter"] = f"lastSeen gt {cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        return params

    def _pages(self, run, progress) -> tuple[list[dict], bool]:
        rows: dict[str, dict] = {}
        complete = True
        seen_links: set[str] = set()
        params = self._base_params(run)
        skip = 0
        body = self.client.get(COLLECTION, params=params)
        for page in range(1, MAX_PAGES + 1):
            batch = body.get("value")
            if not isinstance(batch, list):
                if page == 1:
                    raise SourceError("Defender returned no machine list ('value').")
                self._warn(run, None, f"Page {page} had no machine list; listing stopped.")
                complete = False
                break
            for row in batch:
                if not isinstance(row, dict):
                    continue
                external_id = str(row.get("id") or "").strip()
                if not external_id:
                    self._warn(run, None, "A machine without an ID was skipped.")
                    continue
                if external_id in rows:
                    self._warn(run, external_id, "Listed twice; the first entry was used.")
                    continue
                rows[external_id] = row
            run.checkpoint = f"page {page}, {len(rows)} machines"
            run.devices_total = len(rows)
            progress()
            next_link = body.get("@odata.nextLink")
            try:
                if next_link:
                    if not isinstance(next_link, str) or next_link in seen_links:
                        self._warn(run, None, "Defender repeated a continuation link; stopped.")
                        complete = False
                        break
                    seen_links.add(next_link)
                    body = self.client.get_continuation(next_link)
                elif len(batch) >= PAGE_SIZE:
                    skip += PAGE_SIZE
                    body = self.client.get(COLLECTION, params={**params, "$skip": str(skip)})
                else:
                    break
            except AuthError:
                raise
            except (UnsafeTarget, BudgetExhausted) as exc:
                self._warn(run, None, str(exc))
                complete = False
                break
            except SourceError as exc:
                self._warn(run, None, f"Machine list stopped after page {page}: {exc}")
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
            record, warnings = machine_to_record(
                row, tenant_id=self.instance.tenant_id, fetched_at=fetched_at
            )
            for message in warnings:
                self._warn(run, record["external_id"], message)
            records.append(record)
            run.devices_processed = index
            if index % PROGRESS_EVERY == 0:
                progress()
        run.api_requests = self.client.total_requests
        progress()
        return records, complete

    @staticmethod
    def _warn(run, external_id, message: str) -> None:
        run.warnings += 1
        if len(run.warning_samples) < 20:
            run.warning_samples.append({"external_id": external_id, "warning": message[:300]})


# --- Security state (kept apart from asset fields) ------------------------------------------

TRACKED = (
    "onboarding_status",
    "health_status",
    "exposure_level",
    "risk_score",
    "device_tags",
    "machine_group",
    "entra_device_id",
)


def store_security_states(instance, run, records: list[dict], complete: bool) -> None:
    from apps.observations.models import Observation
    from apps.security.models import EndpointSecurityState

    now = timezone.now()
    by_id = {r["external_id"]: r for r in records if r.get("external_id")}
    latest: dict[str, object] = {}
    for obs_id, external_id in (
        Observation.objects.filter(instance=instance, external_id__in=list(by_id))
        .order_by("external_id", "-received_at")
        .values_list("id", "external_id")
    ):
        latest.setdefault(external_id, obs_id)
    existing = {
        s.external_id: s
        for s in EndpointSecurityState.objects.filter(instance=instance, external_id__in=by_id)
    }
    with transaction.atomic():
        for external_id, record in by_id.items():
            values = security_state(record)
            state = existing.get(external_id)
            if state is None:
                state = EndpointSecurityState(
                    instance=instance, external_id=external_id, changed_at=now
                )
            elif any(getattr(state, key) != values[key] for key in TRACKED):
                state.changed_at = now
            for key, value in values.items():
                setattr(state, key, value)
            state.observation_id = latest.get(external_id)
            state.last_synced_at = now
            state.last_run = run
            state.missing_since = None
            state.save()
        # Only a complete full listing may say a machine is no longer reported, and even
        # then the device may still exist (offboarded, renamed, retention expired).
        if run.mode == "full" and complete:
            EndpointSecurityState.objects.filter(
                instance=instance, missing_since__isnull=True
            ).exclude(external_id__in=list(by_id)).update(missing_since=now)
