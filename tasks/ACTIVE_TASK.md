# Current Task: 010 | Entra/M365 SKU + license assignments

Status: **Provisionally Complete / Fixture-validated only. Live synchronisation NOT activated**
(2026-11-03, branch DEV). Microsoft 365 / Entra source availability is **Beta**.

**Read:** AGENTS.md, docs/00, 03 (licensing entities), 04 (licenses endpoints), 05 (§5,
failure behaviour, fixtures), 06 (software and license model), 08 (§6), 15, 17.

**Previous:** 009 Defender for Endpoint (Provisionally Complete, CI run 41664784779 green on
`f630306`). ADR-014 (Entra device ID auto-link with corroboration) is kept as implemented.

## Scope

- A read-only Graph v1.0 connector for subscribed SKUs and user license assignments
  (direct and group-based).
- Storage of subscription snapshots and allocations that never double-counts a user.
- A license API and a Licenses screen with an SKU drilldown.

Out of scope: entitlements and agreements, software products and installations (Task 016),
billing or compliance calculations, group names, `licenseDetails`, any write to the tenant
and any live connection.

## Outcome

**Connector (`adapters/m365/`):**
- `M365Client` (`GraphClient` subclass): GET only, with continuation links limited to
  `/subscribedSkus` and `/users`.
- Adapter:
  - reads `/subscribedSkus` and paged `/users` (`$select` of ID, UPN, display name,
    enabled, assignedLicenses and licenseAssignmentStates; `$top=999`; nextLink);
  - tracks whether each listing is complete;
  - the connection test reports missing or excess permissions (both required:
    `Organization.Read.All`, `User.Read.All`);
  - it produces no device records: data goes to `apps.licensing` through the
    `store_facts` hook, which now receives the adapter.

**Licensing model (new app `apps.licensing`, ASM-42):**
- `LicenseSku` (per instance).
- Append-only `SubscriptionSnapshot`: reported enabled, warning, suspended, locked-out and
  consumed units, plus ITAM's distinct assigned/direct/group user counts. A new row is
  written only on change; otherwise it is confirmed.
- `DirectoryUser`: minimal identity, licensed users only.
- `LicenseAllocation`: one active row per user and SKU across all paths. Ended, never
  deleted; a re-assignment opens a new row.

**Rules:**
- Only a complete listing ends allocations, flags users or SKUs missing, or produces
  counts; otherwise the counts are "Unknown".
- Assigned users count Active, ActiveWithError and Unknown; not Error or Disabled.
- SKUs assigned but not subscribed are kept without quantities.

**Permissions:** new `licenses.view` (System Admin, ITAM Manager, Auditor;
`accounts.0005_license_permissions`).

**Migrations (all reversible):**
- `licensing.0001_license_inventory`
- `integrations.0010_m365_beta` (Planned → Beta)
- `accounts.0005_license_permissions`

CI reverses `licensing` too.

**APIs (new):**
- `GET /api/v1/licenses/subscriptions/`: latest snapshot, available = enabled − consumed,
  freshness.
- `GET /api/v1/licenses/subscriptions/{id}/`: service plans, up to 100 snapshots.
- `GET /api/v1/licenses/allocations/`: cursor pagination; filters `sku`, `q`, `method`
  (direct / group / direct_and_group) and `include_ended`.

**UI:**
- Navigation item **Licenses**, shown only with `licenses.view`.
- Subscriptions table: purchased, consumed (tenant), assigned users (ITAM), available,
  status, snapshot time and freshness, with an inventory-not-compliance note.
- SKU drilldown: quantity strip, assigned users (method, groups, state, first and last
  seen; filters; load more), quantity history and details.
- Integration page: M365 profile, permission panel and capability labels; a `licenses` run
  phase; the catalogue has the fixed endpoint.
- Numeric table columns are right-aligned.

**Fixtures:** `fixtures/m365/graph/responses.json` holds 5 SKUs (enabled, warning,
suspended, free) and 10 users: direct, group, direct + group, two groups, Error,
ActiveWithError, disabled account, unlicensed, unsubscribed SKU and missing states.

**Config and docs:**
- `ITAM_INTEGRATION_M365_CLIENT_SECRET` (fallback) in Compose and `.env.example`.
- docs/17 DEC-17 and ASM-41 to ASM-43; README section.

## Verification (workstation; SQLite test-only fallback, no Docker/PostgreSQL here)

- **Backend: 529 passed, 6 skipped** (the 6 skips are PostgreSQL/Redis-only). This includes
  25 new tests in `test_m365.py`:
  - GET-only reads and paging; no device records;
  - reported versus counted quantities;
  - direct + group counted once; assignment states; minimal identity;
  - unsubscribed SKU;
  - idempotent confirm; changed purchased units keep history;
  - ended and re-assigned allocations; path change;
  - incomplete user listing (nothing ended, counts Unknown); unsafe link;
  - SKU and user missing flags; allocation helper;
  - 403 naming both permissions; AADSTS error; expired token plus 429;
  - connection test (excess and missing permissions); configuration defaults;
  - subscription and allocation API with filters; `licenses.view` enforcement;
  - no secret or token in logs; scheduler.
- Updated tests: the planned-source tests now create their own planned source (none
  remain seeded).
- Ruff check and format are clean; no migration drift; the OpenAPI schema validates with
  `--fail-on-warn` and matches the committed file.
- Frontend: typecheck, oxlint, **100 tests** (4 new) and the build all pass.
- GitHub CI run 41672076454 on `563abbd` (PostgreSQL 16 + Redis 7): backend **535 passed,
  0 skipped**; migrations applied and reversed (including `licensing`); OpenAPI drift check;
  frontend 100 tests; Compose config and production image builds all pass.
- Not run: the Docker stack, Playwright, a browser review, and **any tenant connection**
  (not authorised).

**Activation prerequisites (not done):**
1. The Docker-host verification passes.
2. DEC-17 is approved: the tenant ID, an app registration with only `Organization.Read.All`
   and `User.Read.All`, a certificate, egress, a sanitized sample, privacy approval for
   UPNs and names (DEC-15) and written approval.
3. Run the connection test; confirm no excess permissions and that
   `licenseAssignmentStates` is returned.
4. Set `ITAM_ALLOW_LIVE_INTEGRATIONS=true`, record the approval, then enable the schedule.

**Outstanding issues:**
- Permission names (including whether `LicenseAssignment.Read.All` suffices) and property
  shapes are from documentation.
- Group names are shown only when the optional `GroupMember.Read.All` is granted (fixed
  2026-11-04, see below); otherwise IDs only.
- No entitlement or agreement data (Task 016).
- Personal-data retention for directory users awaits DEC-15.
- Not load-tested (Task 022).

## Follow-up fixes (2026-11-04)

Open issues from Tasks 008 to 010 that needed no live tenant or policy decision:

1. **Defender rate budget shared** (ASM-37): the per-run counter is replaced by a per-tenant
   sliding-window budget in the Django cache (Redis). It is shared by every run and worker:
   90 calls per minute (the client waits) and 1,400 per hour (the listing stops as
   incomplete). If the cache is down it falls back to a per-process budget.
2. **Group names on license assignments** (ASM-41): these are read only when the token
   holds the optional `GroupMember.Read.All` (or `Group.Read.All` / `Directory.Read.All`):
   one `GET /groups/{id}` per assigning group (GUIDs only, at most 500). A refused or
   failed read only warns. Names are stored in `licensing.DirectoryGroup`
   (migration `licensing.0002_directory_group`). The allocation API adds
   `groups[{id, display_name}]`, and the UI shows the names.
3. **Integration page wording**: Microsoft 365 health and run history say "licensed users",
   hide asset-matching and candidate counts, and link to Licenses. "Re-read" is shown only
   for connectors that re-read details.
4. **Subscriptions list**: snapshots are prefetched in one query instead of one per SKU.

**Verification:**
- Backend: 536 passed, 6 skipped (7 new tests: shared, minute and fallback Defender
  budgets; group names with, without and refused; query count).
- Frontend: 100 tests, typecheck, lint and build pass.

**Still open:** regional Defender hosts (needs a verified host list), whether excess roles
should block syncs, phone and tablet categories (product decision), and DEC-15, DEC-16 and
DEC-17.

Proposed next task: **011 | Reconciliation review and category reclassification**
(tasks/BACKLOG.md). Do not start automatically.
