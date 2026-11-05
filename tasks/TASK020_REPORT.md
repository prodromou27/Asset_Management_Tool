# Task 020 — Administration settings, provider catalogue and operational health

Owner authorized Task 020 on 2026-11-05. Branch DEV, baseline `a8a45b0`.
Task 019 history was archived without implementation changes in `TASK019_OUTCOME.md`.
Requirements: docs/08, 09 and 20; relevant acceptance A21/A22 and administration gate G5.

## Delivered

- General organization settings at `/admin/general` and `GET/PATCH /api/v1/settings/general/`:
  organization name, IANA display timezone, date format, English and optional support email.
  Model singleton, validated/allowlisted fields, row-locked If-Match/version check, before/
  after audit, no-op handling, admin edit and admin/auditor view permissions. Unsupported
  fields and deployment controls are rejected. Stale edits offer explicit reload.
- Authenticated session responses carry only the safe display subset. Shared formatting
  and sidebar branding follow the saved policy. Calendar-only dates never shift. Browsers
  that lack a configured timezone show an explicit UTC fallback warning. Language remains
  English; schedules/UTC storage and per-domain retention remain unchanged.
- Integrations retain existing instance creation/edit/test/sync/field-authority workflows.
  Provider catalogue tab supports name/description search and availability/configuration
  filters, preserves selected tab in the URL, and distinguishes adapter maturity,
  implemented adapter, configured-instance count and required read permissions. Planned
  providers are not presented as working connections. Source-load failures are visible.
- `GET /api/v1/health/operations/`: protected by `health.view`, read-only/no-store,
  with database/Redis probes, scratch capacity, recorded integration freshness/gates,
  SMTP and backup evidence, durable job counts and an actionable first-run checklist.
  No vendor, SMTP or repository probes; no configuration/secret rows created by health
  reads. SMTP retry/backlog logic reuses the existing notification service. Import states
  include previewing/committing. Unknown/manual production gates remain Incomplete.
- Existing users/sites/categories/security/SMTP/backups/lifecycle pages are reused.
  Deployment-owned and planned settings are described without ineffective controls.

## Permissions and migrations

- `accounts.0014_generalsettings`: reversible additive singleton table.
- `accounts.0015_admin_permissions`: General view/manage and health view permissions.
- System admin: all three. Auditor: General view and health view. ITAM manager,
  infrastructure engineer and security analyst: health view, per docs/09.
- Existing authentication/current-password guard, session/CSRF, audit and site permissions
  are retained. Health exposes aggregate operational metadata, not business rows, endpoints,
  credential references, filesystem paths, raw errors or backup contents. Links are only
  actionable when the viewer has the target screen's permission.

## Verification

Local environment has Python/Node/Edge; Docker/PostgreSQL/Redis are unavailable locally.
Full backend: **810 passed, 7 PostgreSQL/Redis-only skips**, explicit SQLite fallback.
After SMTP reuse, focused health/notification suite: **31 passed**. Provider contract
regression passed. General tests cover permissions, unknown/invalid fields, version
conflicts, effective display policy, audit and no-op. Diagnostics cover missing/unavailable
database, safe partial-failure handling, approval/disabled/stale source states and SMTP retry.

Full frontend: **200 passed**; subsequent settings/shell suite **22 passed**, including the
added unsupported-browser-timezone regression (201 total tests now). Tests cover save/body/
If-Match, branding, validation/draft retention, stale reload, auditor/denied access, catalogue
filters, diagnostics permission and truthful production/worker states. Typecheck, oxlint,
production build, Ruff lint/format, migration drift and validated OpenAPI generation passed.
The existing frontend bundle-size warning remains; no performance improvement is claimed.

`pnpm review:ui`: **41 screenshots**, real headless Edge at 1440×900 and 390×844, with
synthetic fixtures only and all non-loopback networking blocked. Covers the existing
application plus General settings, validation/saved/denied states, a long organization
name, provider catalogue, operational diagnostics and unsupported-timezone fallback.
No browser exceptions, unmapped
requests or document overflow. Inspected General desktop/saved, operational desktop and
provider mobile screenshots; refined section insets, numeric alignment, readable mobile
provider-name columns and ellipsized sidebar names. Local artifacts are ignored under
`frontend/test-results/task020-review/`.

Commands: backend `python -m pytest -q -p no:cacheprovider`, focused suites, `ruff check`,
`ruff format --check`, `manage.py makemigrations --check --dry-run`, `manage.py spectacular
--validate --fail-on-warn`; frontend `pnpm gen:api`, `pnpm test`, focused `pnpm exec vitest
run ...`, `pnpm typecheck`, `pnpm lint`, `pnpm build`, `pnpm review:ui`.

[CI run 42058286320](https://github.com/prodromou27/Asset_Management_Tool/actions/runs/42058286320)
passed on implementation **79469ba**: **818 PostgreSQL/Redis backend tests, no skips;
201 frontend tests**. Migration drift/apply/reversal, OpenAPI/type drift, Ruff lint/format,
frontend lint/typecheck/build, production settings deploy check, dev/prod Compose validation,
production API/frontend and restricted backup-worker image builds, and the existing real
encrypted SFTP/isolated restore proof all passed. That restore uses a new network-disabled
PostgreSQL after deleting the synthetic source database/storage; it does not restore user
or production data. Local Docker limitations are covered by this actual CI execution.

Task 020 is complete. Documentation-only follow-up records this result; no production
service, credential, destination or live integration was enabled.

## Deliberate limits and next action

This is operational evidence, not a production approval workflow. There are no worker
heartbeats, automatic production-ready certification, raw host-log viewer, remote storage
capacity probe, IdP/MFA implementation, new retention deletion or live commissioning.
These need approved target-host/identity/retention decisions and the staging pilot.
Scratch capacity is not PostgreSQL/off-host capacity. Historical failed job totals are
not current worker failure counts. Disabled sources do not count as successful syncs.
DEC-09 and other operator gates remain open; production backup/live-access gates stay off.
Next: verify CI, then review Task 021 separately. Task 021 has not been started.
