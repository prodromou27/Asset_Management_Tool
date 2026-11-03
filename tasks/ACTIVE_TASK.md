# Current Task: 005 | Asset list/detail UI, search, filters, provenance drawer

Status: **In progress** (started 2026-11-03 on branch DEV).

**Read:** AGENTS.md, docs/00, 04, 07, 08 (backlog list for 005).

## Re-scope (owner approved "proceed" on the proposal in the Task 004 report)

List, detail, URL filters, search and the Source evidence tab already exist (Tasks 003–004).
Task 005 delivers what docs/07 AssetTable and SourceEvidenceDrawer still require:

1. Saved views (personal; shareable by users with asset edit rights), applied via URL.
2. Column chooser, remembered per user.
3. Last seen and Sources columns; filters by source integration and observation status.
4. Source evidence drawer opened from technical fields on the asset Overview.
5. Search/list performance at 10k assets: PostgreSQL trigram indexes and a timed
   PostgreSQL test (docs/14 p95 < 2 s target, single-request approximation).

Out of scope: bulk edit/selection toolbar (Task 012 groups / 013 imports), exports (014),
column width persistence.

## Acceptance

- Saved views never widen site scope (filters always run through `visible_assets`).
- Only the owner edits/deletes a view; shared views are read-only to others.
- Unknown filter keys, columns or ordering in a view are rejected (422).
- List query count stays bounded with the new annotations.
- 10k-asset list, count and search each complete within budget on PostgreSQL CI.
- Drawer: keyboard reachable, Escape closes, focus returns to the trigger.

---

## Task 004 | Discovery Observations and Asset Identity (previous)

Status: **Provisionally Complete / Pending Docker host verification** (2026-11-03, branch DEV).

**Read:** AGENTS.md, docs/00, 03, 05, 14, 15 (backlog list), plus 04, 07, 08 for API/UI.

## Outcome

Commits on DEV: `6fe6bf3` (backend), `f162ab0` (frontend, fixtures, docs).

**Migrations:** `accounts.0004_discovery_permissions` (5 permissions + role grants),
`integrations.0001` (DiscoverySource, IntegrationInstance, SyncRun, FieldAuthorityPolicy),
`integrations.0002_seed_sources_and_policy` (vendor sources Planned, fixture Available,
default precedence), `observations.0001` (Observation), `observations.0002` (append-only
trigger), `assets.0004` (AssetIPAddress site/VRF, new history types, fixture source),
`assets.0005` (FieldProvenance, FieldLock), `reconciliation.0001` (SourceLink,
ReconciliationCandidate, FieldConflict, AssetMerge). All reversible (verified).

**Behaviour:** immutable checksummed observations with normalisation (vendor aliases,
placeholder serials → unknown, MAC/IP/hostname/OS/firmware, IP site/VRF context);
idempotent ingestion with per-record savepoints and sync history; instance-scoped links;
matching (strong: verified manufacturer+serial, hardware UUID; corroborating: MAC,
hostname, IP same site/VRF; never auto-merge on weak keys; conflicts → review);
candidate decisions link/create/hold/reject; unlink reopens review; reversible merges;
field provenance, manual locks (automatic on manual edits), conflicts, source precedence;
stale marking (full error-free runs + hourly Celery task), never deletion; field-level
permissions closing ASM-09. No vendor API calls, no scanning, no HTTP ingestion endpoint.

**APIs (21 new paths, 57 total):** `/discovery/sources/`, `/discovery/candidates/` (+ `{id}/`),
`/reconciliation/{id}/approve|reject|hold/`, `/discovery/observations/` (+ `{id}/`),
`/discovery/conflicts/` (+ `{id}/resolve/`), `/discovery/field-authority/`,
`/integrations/` (+ `{id}/`, `{id}/runs/`), `/assets/{id}/evidence/`, `/assets/{id}/observations/`,
`/assets/{id}/field-locks/` (+ `unlock/`), `/assets/{id}/merge/`, `/source-links/{id}/unlink/`,
`/merges/{id}/revert/`. Command: `manage.py load_observations`.

**UI:** Discovery (queue, field conflicts, sources/freshness/sync history), candidate
detail and decision, asset Source evidence tab, Administration → Integrations with field
authority editor.

**Verification:**
- GitHub CI run 41592967221 (PostgreSQL 16 + Redis 7): backend **304 passed, 0 skipped**;
  migrations apply/reverse/re-apply; OpenAPI valid and in sync; `check --deploy` clean;
  frontend types in sync, lint, typecheck, **68 tests**, build; Compose valid, images build.
- Workstation (SQLite test-only): backend 299 passed, 5 skipped (PostgreSQL-only).
- Acceptance covered by tests: docs/15 A01, A02, A03, A04, A08, A23 (no-IP UPS fixture).
- Not run: Docker dev stack, Playwright, manual browser review of the new screens.

**Unresolved / assumptions** (docs/17 ASM-13..18): no real adapters (Tasks 006–010 map
vendor payloads to the source record); raw observation retention unbounded until DEC-15;
lower-authority disagreements are evidence, not conflicts; merges move only links and
discovered identifiers; candidate list has no free-text search; topology/FDB evidence not
modelled yet (docs/05 A24).

## Pending verification (Docker host) — Tasks 001–004

Task 003 list below, plus: create a fixture integration, `load_observations` the sanitized
fixture twice (second run unchanged), decide candidates in the UI, edit a discovered field
as Asset Operator (expect 403) and as Infrastructure Engineer (expect lock), re-load a
changed fixture and resolve the conflict, confirm worker/beat run the freshness task.

Proposed next task: **005 | Asset list/detail UI, search, filters, provenance drawer**
(tasks/BACKLOG.md). Much of 005 now exists; consider re-scoping it to saved views,
column chooser and query-performance work at 10k assets. Do not start automatically.

---

## Task 003 | Core Asset Management (previous)

Status: **Provisionally Complete / Pending Docker host verification** (2026-11-02, branch DEV).

**Read:** AGENTS.md, docs/00, 01, 03, 04, 07, 08 (backlog list for 003).

## Objective

Canonical asset register with site-scoped RBAC: assets (UUID, tag, identity, hardware,
OS/firmware, category, site/location/department, owner, three status dimensions,
notes), hierarchical categories with typed custom fields, sites/locations/departments,
multiple interfaces/MACs/IPs/hostnames with source fields, append-only history,
soft archival, optimistic locking. Closes ASM-04 (site-scoped authorization).

## Out of scope

LibreNMS/discovery, EOL data, licensing, dynamic groups, agents, import/export jobs.

## Acceptance

- Users never see or change assets outside granted sites via URL, filter or payload.
- Create/edit/reclassify/reassign/archive/restore recorded in asset history and audit.
- PATCH and state changes require If-Match; stale versions return 409.
- No hard delete; archived assets hidden by default and read-only until restored.
- IP, MAC, serial and hostname optional; no global uniqueness on them.
- PostgreSQL CI green; OpenAPI and generated frontend types in sync.

## Outcome (2026-11-02)

Commits on DEV: `7a6b87e` (backend), `df9458a` (frontend + docs).

**Migrations:** `accounts.0003_asset_permissions_and_site_scope` (User.all_sites, 7 new
permissions, role grants, existing System Admins → all sites), `organizations.0001_initial`
(Site, Location, Department, UserSiteGrant), `assets.0001_initial` (AssetCategory,
CustomFieldDefinition, Asset, AssetInterface, AssetIPAddress, AssetHostname,
AssetHistoryEntry), `assets.0002_seed_categories`, `assets.0003_history_append_only_trigger`.
All reversible (verified to zero and back, SQLite and PostgreSQL).

**Endpoints (19 new paths, 36 total):** `/assets/` (GET list with filters/ordering, POST),
`/assets/{id}/` (GET, PATCH + If-Match), `/assets/{id}/classification/` (POST + If-Match),
`/assets/{id}/classification/preview/`, `/assets/{id}/archive/`, `/assets/{id}/restore/`,
`/assets/{id}/history/`, `/asset-categories/` (+ `{id}/`, `{id}/fields/?effective=`),
`/custom-fields/{id}/`, `/sites/` (+ `{id}/`), `/locations/` (+ `{id}/`), `/departments/`
(+ `{id}/`), `/users/lookup/`; `/users/{id}/` PATCH now takes `all_sites`, `site_ids`.

**UI:** Assets list, asset detail (Overview/Network/History tabs, 3 status dimensions,
reclassify/archive/restore dialogs), asset create/edit, Categories & fields, Sites &
locations & departments, Site access panel on user detail.

**Verification:**
- GitHub CI run 41517885491 (PostgreSQL 16 + Redis 7): backend **217 passed, 0 skipped**;
  migrations apply/reverse/re-apply; OpenAPI valid and in sync; `check --deploy` clean;
  frontend types in sync, lint, typecheck, **57 tests**, build; Compose dev/prod valid,
  prod only 443, images build.
- Workstation (SQLite test-only): backend 213 passed, 4 skipped (PostgreSQL-only).
- Not run: Docker dev stack, Playwright e2e, manual browser check of the new screens.

**Unresolved / assumptions** (docs/17): ASM-08 owners must be user accounts; ASM-09 no
field masks yet; ASM-10 custom values in JSONB with typed validation; ASM-11 free-text
manufacturer/model; ASM-12 manual-only network edits. Department scoping not
implemented. No bulk edit/import/export (Tasks 013–014). Owner lookup capped at 200
active users.

## Pending verification (Docker host) — Tasks 001–003

Same list as Task 002 below, plus: create sites/locations, grant a user one site, sign in
as that user and confirm assets of other sites are absent from list, search and direct
URLs; register, edit, reclassify, archive and restore an asset and check its History tab.

Proposed next task: **004 | Source observations, identity matching and manual field
locks** (tasks/BACKLOG.md). Do not start it automatically.

---

## Task 002 | Named Admin Bootstrap, Local Auth/RBAC + Audit (previous)

Status: **Provisionally Complete / Pending Docker and PostgreSQL Verification.**

Started on 2026-11-02 at the owner's explicit request while Task 001 was still pending
Docker verification. Neither task may be marked Complete until the "Pending
verification" items below have been run on a Docker host and the real output recorded.

**Read:** AGENTS.md, docs/00, 03, 04, 09, 14 (backlog list) plus 07, 08 for the UI.

## Outcome (2026-11-02)

Backend (`apps/accounts`, `apps/audit`, `config/api.py`, `config/request_context.py`):

- Custom UUID `User` (lowercase unique username, case-insensitive unique email,
  version, lockout fields, `session_epoch`), `Role`, `Permission`, `SecuritySettings`.
- Seed migration: 7 documented roles; 6 permission codes; System Admin holds all,
  Auditor holds users.view/roles.view/audit.view/settings.security.view; others none yet.
- `manage.py bootstrap_admin` — named System Admin, password via TTY prompt or
  `--password-stdin` only, audited as `cli:<os user>`; supports second emergency admin.
- Auth API: `/auth/csrf`, `/auth/providers`, `/auth/local/login` (CSRF-protected,
  10/min/IP throttle, generic failure, per-account lockout, session rotation),
  `/auth/logout`, `/auth/me`, `/auth/password/change`.
- Sessions: HttpOnly SameSite=Lax cookies; admin-configurable idle and absolute
  timeouts enforced per request; disable/reset bumps `session_epoch` → all sessions
  revoked; password change revokes other sessions; inactive users rejected.
- Argon2 primary hasher; configurable minimum length + Django similarity/common/numeric.
- Temporary passwords: `must_change_password` blocks every endpoint except me,
  logout and password change.
- Users API: list (cursor, q/status/role filters), create, get, PATCH (If-Match →
  428/409), disable (reason required), enable, unlock, reset-password. Guards:
  no self-disable, no self-demotion, last active System Admin cannot be removed.
- `GET /roles`, `GET /permissions`, `GET/PATCH /settings/security` (If-Match, bounds,
  idle ≤ absolute).
- Audit: append-only model + PostgreSQL trigger (UPDATE/DELETE/TRUNCATE blocked),
  secret-key redaction, request ID, actor, IP, before/after; `GET /audit/events`
  with filters. Logged: login success/failure, lockout, logout, session expiry,
  password change/reset, user create/update/disable/enable/unlock, bootstrap,
  security-settings change.
- Error envelope `{error: {code, message, request_id, field_errors}}`; 401 vs 403;
  422 for validation; `X-Request-ID` on every response.
- Task 001 fixes found on the way: readiness no longer leaks driver/host errors to
  anonymous callers; frontend now shows a degraded (503) readiness body instead of
  a generic failure.
- Proxy-aware client IP (`ITAM_TRUSTED_PROXY_COUNT`, 1 in prod): login throttling and
  audit IPs use the nginx-appended hop; client-supplied X-Forwarded-For is ignored.

Frontend:

- Typed client generated from OpenAPI (`openapi.yaml` → `schema.d.ts`); CSRF header,
  If-Match, error envelope parsing; global 401 → back to sign-in.
- Screens: Sign in, Change password (forced for temporary passwords), Users & roles
  list/detail/create, Audit log, Security policy. Permission-filtered navigation;
  routes also guarded; API remains the authority.
- Shared accessible UI: labelled fields with aria-describedby errors, focused error
  summary, `<dialog>` confirmations naming the affected count, text+colour status
  badges, loading/empty/error/denied states, URL-encoded filters, cursor "Load more".

## Verification run on this workstation (no Docker; SQLite test-only per ASM-02)

- Backend: `pytest` **104 passed, 3 skipped** (the 3 need PostgreSQL/Redis);
  ruff check + format clean; `makemigrations --check` clean; `migrate`,
  `migrate --check`, reverse to zero and re-apply clean; `spectacular --validate
  --fail-on-warn` clean (18 paths); committed schema in sync.
- Frontend: vitest **38 passed** (no act/console warnings); oxlint clean; `tsc -b`
  clean; production build OK.
- Not run here: Playwright e2e (no browser/stack).

## GitHub CI (2026-11-02, branch DEV, run 41511768274) — green

Repository: https://github.com/prodromou27/Asset_Management_Tool (private).

- Backend on **PostgreSQL 16 + Redis 7**: **107 passed, 0 skipped** (includes the
  unmocked readiness integration tests and the audit append-only trigger test);
  migrations apply, `migrate --check`, reverse to zero and re-apply; OpenAPI valid and
  in sync; production `check --deploy` no issues.
- Frontend: generated types in sync, lint, typecheck, 38 tests, build.
- Compose: dev and prod `config` valid; prod publishes only 443, no Mailpit, DEBUG off;
  production api and frontend images build.
- CI found two PostgreSQL-only defects that the SQLite workstation run could not:
  hard-coded `itam_test` DB name in test settings, and `%` in the audit trigger DDL
  being treated as a placeholder. Both fixed on DEV.
- `main` still has the first (red) run until DEV is merged.

## Pending verification (requires Docker host) — covers Tasks 001 and 002

1. `scripts/compose.sh dev config --quiet` and `scripts/compose.sh prod config --quiet`.
2. `scripts/compose.sh dev up -d --build`; postgres, redis, api, worker healthy in `ps`.
3. `scripts/migrate.sh dev` succeeds against PostgreSQL (includes audit trigger).
4. `/api/v1/health/ready/` 200 with database/redis `up`; 503 with database `down`
   after `scripts/compose.sh dev stop postgres`.
5. Worker answers `celery -A config inspect ping`; scheduler starts beat cleanly.
6. `scripts/bootstrap_admin.sh dev <user> "<name>"` creates admin; second admin too.
7. Sign in at http://localhost:5173 through the Vite proxy (CSRF origin check),
   create a user, sign in as that user, forced password change, disable from admin
   and confirm the user's session ends.
8. `scripts/compose.sh dev run --rm -e DJANGO_SETTINGS_MODULE=config.settings.test api
   python -m pytest -q -rs` — **107 passed, 0 skipped** (already proven on PostgreSQL in
   CI; this confirms the dev container image).
9. Production images build; `compose.prod.yaml` published ports are 443 only.
10. ~~First CI run green~~ Done on DEV (run 41511768274); merge DEV → main and confirm.

## Known gaps / blockers (recorded in docs/17_ADR_OPEN_DECISIONS.md)

- ASM-03: no MFA/OIDC yet; DEC-11 must be decided before production.
- ASM-04: no site/department scoping until sites exist (Task 003).
- ASM-05: role→permission grants are seeded, not editable in the UI yet.
- Admin-only "session list" and account-access-review export are not implemented.

Proposed next task: **003 | Asset/category/site schema + CRUD** (tasks/BACKLOG.md),
only after the pending verification above. Do not start it automatically.

---

## Task 001 | Bootstrap Secure Local Stack — status

**Provisionally Complete / Pending Docker and PostgreSQL Verification** (same list
above). Django 5.2.18 LTS; DRF 3.18.3; drf-spectacular 0.30.0; Celery 5.6.3;
redis-py 6.4.0; psycopg 3.3.6; gunicorn 26.2.0. Compose and CI YAML have only been
syntax-checked; that is not runtime validation.
