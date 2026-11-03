"""Microsoft 365 / Entra license adapter (Graph v1.0, application permissions).

Reads, GET only:
- ``/subscribedSkus``: the tenant's subscribed SKUs with purchased (prepaid) and consumed
  units. Needs ``Organization.Read.All``.
- ``/users?$select=id,userPrincipalName,displayName,accountEnabled,assignedLicenses,
  licenseAssignmentStates&$top=999``: user license assignments including the
  group-based paths, following ``@odata.nextLink``. Needs ``User.Read.All``.

``licenseDetails`` is not used (docs/05), group display names are not read (that would
need group permissions), and nothing is written to the tenant. No device records are
produced: the data goes to ``apps.licensing`` through ``store_license_data``.

A listing is complete only when its last page has no next link; an incomplete user
listing never ends allocations or flags users missing, and leaves ITAM's assigned-user
counts unknown for that run.
"""

from collections.abc import Callable

from ..base import AuthError, SourceError, UnsafeTarget
from ..intune.adapter import excess_roles
from .client import REQUIRED_PERMISSIONS, M365Client

SKUS = "/subscribedSkus"
USERS = "/users"
USER_SELECT = (
    "id,userPrincipalName,displayName,accountEnabled,assignedLicenses,licenseAssignmentStates"
)
PAGE_SIZE = 999
MAX_PAGES = 2000


def permission_summary(roles: list[str] | None) -> tuple[dict, str]:
    excess = excess_roles(roles)
    missing = [p for p in REQUIRED_PERMISSIONS if roles is not None and p not in roles]
    caps = {
        "subscribed_skus": True,
        "license_assignments": True,
        "group_names": False,
        "permission_read_all": not missing,
        "excess_permissions": bool(excess),
    }
    warnings = []
    if excess:
        warnings.append(
            "The app registration also holds write or privileged permissions "
            f"({', '.join(excess)}). The connector never uses them; remove them so the "
            f"application has only {' and '.join(REQUIRED_PERMISSIONS)}."
        )
    if missing:
        warnings.append(f"The access token does not list {', '.join(missing)}.")
    return caps, " ".join(warnings)


def test_connection(client: M365Client) -> dict:
    client.get(SKUS)
    client.get(USERS, params={"$select": "id", "$top": "1"})
    caps, warning = permission_summary(client.tokens.roles)
    return {
        "version": "Microsoft Graph v1.0",
        "capabilities": caps,
        "requests": client.total_requests,
        "warning": warning,
    }


class M365Adapter:
    def __init__(self, instance, client: M365Client, capabilities: dict | None = None):
        self.instance = instance
        self.client = client
        self.caps = capabilities or instance.capabilities or {}
        self.skus: list[dict] = []
        self.users: list[dict] = []
        self.skus_complete = False
        self.users_complete = False

    def prepare(self) -> None:
        """Nothing to detect."""

    def _collection(self, run, progress, path, params, label) -> tuple[list[dict], bool]:
        rows: dict[str, dict] = {}
        seen_links: set[str] = set()
        body = self.client.get(path, params=params)  # first page errors fail the run
        for page in range(1, MAX_PAGES + 1):
            batch = body.get("value")
            if not isinstance(batch, list):
                if page == 1:
                    raise SourceError(f"Microsoft Graph returned no {label} list ('value').")
                self._warn(run, None, f"{label.capitalize()} page {page} had no list; stopped.")
                return list(rows.values()), False
            for row in batch:
                key = ""
                if isinstance(row, dict):
                    key = str(row.get("skuId" if path == SKUS else "id") or "").strip()
                if not key:
                    self._warn(run, None, f"A {label} entry without an ID was skipped.")
                    continue
                if key in rows:
                    self._warn(run, key, f"{label.capitalize()} listed twice; first entry used.")
                    continue
                rows[key] = row
            run.checkpoint = f"{label}: page {page}, {len(rows)} entries"
            progress()
            next_link = body.get("@odata.nextLink")
            if not next_link:
                return list(rows.values()), True
            if not isinstance(next_link, str) or next_link in seen_links:
                self._warn(run, None, f"Graph repeated a {label} continuation link; stopped.")
                return list(rows.values()), False
            seen_links.add(next_link)
            try:
                body = self.client.get_continuation(next_link)
            except AuthError:
                raise
            except UnsafeTarget as exc:
                self._warn(run, None, str(exc))
                return list(rows.values()), False
            except SourceError as exc:
                self._warn(run, None, f"{label.capitalize()} list stopped after page {page}: {exc}")
                return list(rows.values()), False
        self._warn(run, None, f"{label.capitalize()} list stopped after {MAX_PAGES} pages.")
        return list(rows.values()), False

    def collect(self, run, progress: Callable[[], None]) -> tuple[list[dict], bool]:
        run.phase = "licenses"
        progress()
        self.skus, self.skus_complete = self._collection(run, progress, SKUS, None, "SKU")
        users, self.users_complete = self._collection(
            run, progress, USERS, {"$select": USER_SELECT, "$top": str(PAGE_SIZE)}, "user"
        )
        self.users = users
        licensed = [
            u for u in users if u.get("assignedLicenses") or u.get("licenseAssignmentStates")
        ]
        run.devices_total = len(licensed)
        run.devices_processed = len(licensed)
        _, warning = permission_summary(self.client.tokens.roles)
        if warning:
            self._warn(run, None, warning)
        run.api_requests = self.client.total_requests
        progress()
        # No device records: license data is stored by store_license_data.
        return [], self.skus_complete and self.users_complete

    @staticmethod
    def _warn(run, external_id, message: str) -> None:
        run.warnings += 1
        if len(run.warning_samples) < 20:
            run.warning_samples.append({"external_id": external_id, "warning": message[:300]})
