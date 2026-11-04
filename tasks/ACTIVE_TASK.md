# Current Task: UI redesign - application shell and visual system (before 014)

Status: **Complete locally; awaiting CI** (2026-11-04, branch DEV). Owner feedback: "I
don't like the UI" - plain/dated, colours, layout/navigation. Owner chose the dark navy
sidebar direction, light mode only, and to redesign before Task 014.

**Read:** AGENTS.md, docs/00, 07 (whole), 08 (shell), 15 (UI quality gate).

## Outcome

- **Design tokens** (`tokens.css`, docs/07 updated): navy sidebar, blue accent #2563EB,
  refreshed neutrals, muted surface, strong border, backdrop, nav colours, surface shadow.
  Hard-coded colours in `global.css` replaced by tokens.
- **Fonts and icons bundled** (no CDN, works on isolated networks): Inter Variable, IBM
  Plex Mono 400/500, Lucide icons (one family). New dependencies `@fontsource-variable/inter`,
  `@fontsource/ibm-plex-mono`, `lucide-react`.
- **Shell** (`AppShell.tsx`, new `navigation.ts`):
  - dark sidebar with brand mark, sections Inventory / Sources / Administration / System,
    icons on every entry and an active marker; sections with no permitted entries are hidden;
  - top bar with section / page context, asset search (goes to `/assets?q=`; hidden without
    `assets.view` or with a temporary password) and a user menu with initials and roles;
  - below 768px the sidebar becomes an overlay drawer (menu button, close button, backdrop,
    Escape closes).
- **Components:** page title, panels (8px radius, faint shadow), buttons (6px radius, hover
  states), inputs (focus halo), tables (uppercase header band, hover tint, asset rows on one
  line with sideways scroll), status badges (pill with dot, text darkened to keep AA
  contrast), dialogs, sign-in screen (navy band, raised panel).
- Docs: docs/07 tokens, typography, icons, radii and layout.

## Verification

- Frontend: typecheck, oxlint, **134 tests** (12 new in `AppShell.test.tsx`: navigation
  placement, grouped sections and active state, user menu, top-bar search, search hidden
  without permission, drawer open/close/Escape) and the production build pass.
- Screenshots with mocked data via Playwright + system Edge at 1440x900 and 390x844 (assets
  list with 28 rows, system health, mobile drawer); temporary harness not committed. The
  first round showed wrapped asset rows, fixed to one line.
- Contrast computed for every token pair: all text >= 4.5:1; badge text 5.3-6.2:1 after the fix.
- Bundle +11 kB JS (the pre-existing >500 kB chunk warning is unchanged); fonts are separate files.
- Not done: page-by-page restyle beyond shared components (pages use the shared classes);
  dark mode (deferred by owner).

Proposed next task: **014 | CSV/XLSX/JSON exports with RBAC and async jobs**
(tasks/BACKLOG.md). Do not start automatically.

---

# Previous record: Simple installation

Status: **Complete (CI run 41811176901 green)** (2026-11-04, branch DEV). Owner request: make
the installation simpler, run on port 80 without a certificate, and let an administrator
add a certificate later. Replaces the earlier five-script staging kit.

## Outcome

- `ITAM_PUBLIC_SCHEME=http|https` (default https; ASM-51):
  - Django: http turns off the HTTPS redirect, HSTS and secure cookies, and silences
    only those deploy checks. `ITAM_ENV=production` refuses http.
  - Proxy: `infra/nginx/http.conf` serves the app on 80; `https.conf` (was `prod.conf`)
    serves 443 and redirects 80. nginx-proxy publishes 80 and 443; the certificate
    directory defaults to an empty placeholder.
- `scripts/install.sh`: one command for install and update. Installs Docker if missing
  (official repository, signing-key fingerprint checked), writes `.env` with generated
  secrets on first run (http, server IP), builds, migrates, starts, opens http in
  firewalld, checks health and offers to create the first admin.
- `scripts/enable_https.sh <fullchain> <privkey> [hostname]` or `--self-signed`: checks
  that the key matches and the certificate has not expired, installs to `/etc/itam/tls`,
  switches `.env` (backup kept), opens https and restarts.
- Removed `scripts/staging/`. docs/12 section 9 rewritten; README; `.env.example`;
  docs/17 ASM-51. CI checks ports 80,443 and that http mode selects `http.conf`.
- Kept from the previous step: api healthcheck fix and `CSRF_TRUSTED_ORIGINS` passthrough.

## Verification (workstation; no Docker or AlmaLinux host here)

- Backend 613 passed, 6 skipped (PostgreSQL/Redis-only). New production-settings tests:
  http mode turns off TLS-only settings; http with `ITAM_ENV=production` and an unknown
  scheme are refused.
- `check --deploy --fail-level WARNING` passes in both modes. Ruff clean. `bash -n` on
  both scripts.
- GitHub CI run 41811176901 on `ce1a7ee`: backend **619 passed, 0 skipped**, frontend 122,
  Compose config (ports 80,443; http mode selects http.conf) and image builds pass.
- Not run: the scripts on AlmaLinux or the Docker stack.

---

# Previous record: Task 013

Status: **Complete (CI run 41797570026 green)**
(2026-11-04, branch DEV).

**Read:** AGENTS.md, docs/00, 04 (Import/export endpoints, idempotency), 08 (§10 Import/Export
Center), 09 (role matrix), 11 (Import), 14 (untrusted upload, formula injection), 15 (A13,
A23), 17.

**Previous:** 012 static/dynamic groups (CI run 41793548771 green: backend 588 passed,
frontend 116).

## Scope

- Import framework: templates, upload, mapping, dry run, commit, receipt, error report and
  rollback.
- Families for the entities that exist now: assets, locations, groups and static group
  memberships.

Out of scope:
- The other docs/11 families (categories, manufacturers/models, software entitlements,
  domains, TLS endpoints, relationships) arrive with their tasks.
- Exports are Task 014.

## Outcome

**Parsing (`apps/imports/parsing.py`, ASM-49):**
- CSV: UTF-8/BOM or Windows-1252; delimiter sniffed.
- XLSX: openpyxl read-only with defusedxml; zip-bomb, path and macro checks.
- Limits: 5 MB, 10,000 rows, 100 columns, 10,000 characters per cell.
- Duplicate or blank headers and binary data are refused.
- Formula detection, and cell escaping on all outputs.

**Storage:** the original file is kept Fernet-encrypted (`crypto.py`) until
`ITAM_IMPORT_RETENTION_DAYS` (default 90), then purged by a daily Celery beat task; row
results remain.

**Models:**
- `ImportJob`: status flow, mode, mapping, totals, warnings, checksum, idempotency key,
  committer and rollback.
- `ImportRow`: planned action, key, target, messages, values, changes, result and
  version after.

**Families (ASM-50):**
- **Assets:**
  - matches on id or asset tag only;
  - manufacturer + serial and name + site are review-only conflicts; never hostname/IP;
  - in-file duplicates are conflicts;
  - blank cells mean no change; category changes are refused;
  - locked fields become conflicts; discovery-sourced values need technical rights;
  - site scope; `cf.<key>` custom fields with required-field enforcement;
  - create, update and rollback use the existing asset services (history, audit).
- **Locations:** site + name.
- **Groups:** name; dynamic rules validated.
- **Static memberships:** add only.

**Workflow:**
- Upload: suggests a mapping (names, labels, aliases, `cf.`) and warns when the exact file
  was imported before.
- Mapping and mode changes invalidate the preview.
- Preview is a dry run with no business writes, giving totals per action.
- Commit needs `X-Idempotency-Key` (a repeated key returns the original job) and If-Match.
  Each row is re-planned against current data and applied in its own savepoint; a row
  whose plan changed since the preview fails and the others continue.
- Rollback archives created records and restores updated ones only where unchanged since
  the import; the rest are listed for supervised correction.
- Missing rows never delete anything.
- Audit entries: `imports.upload`, `imports.commit`, `imports.complete`,
  `imports.rollback`.

**Permissions:** new `imports.run` (System Admin, ITAM Manager, Asset Operator;
`accounts.0007`) plus the family permission (assets create/edit, `sites.manage`,
`groups.manage`, `groups.members`) and site scope. Jobs are visible to their uploader, and
read-only to `audit.view` holders.

**Migrations (reversible; CI reverses `imports`):**
- `imports.0001_import_jobs`
- `imports.0002_widen_row_target`: a CI fix, see below
- `accounts.0007_import_permission`

**APIs:**

| Method | Path | Notes |
|---|---|---|
| GET | `/imports/templates/` | Template list |
| GET | `/imports/templates/{family}/csv/` | CSV template download |
| GET, POST | `/imports/` | POST is a multipart upload |
| GET, PATCH | `/imports/{id}/` | PATCH sets mapping and mode |
| POST | `/imports/{id}/preview/` | Dry run |
| GET | `/imports/{id}/rows/` | Filters `action`, `result` |
| GET | `/imports/{id}/errors/` | CSV report |
| POST | `/imports/{id}/commit/` | Needs If-Match and X-Idempotency-Key |
| POST | `/imports/{id}/rollback/` | Needs If-Match and a reason |

**Frontend:**
- The API client sends `FormData` and extra headers.
- **Imports** page (history) in the sidebar, plus an Import button on the Assets page.
- Wizard:
  1. Choose: family, template download and column help, file.
  2. Map: column → field with sample values, and mode.
  3. Dry run: totals, rows with messages and change details, report download, change
     mapping, "Import N rows".
  4. Import: progress, then a receipt with results, checksum, retention, report and
     rollback with a reason.

**Config:**
- nginx `client_max_body_size 6m` on `/api/`.
- `ITAM_IMPORT_ENCRYPTION_KEY` and `ITAM_IMPORT_RETENTION_DAYS` in Compose and
  `.env.example`.
- New dependencies `openpyxl` and `defusedxml`.

**Docs:** docs/17 ASM-49 and ASM-50; README section.

## Verification (workstation; SQLite test-only fallback, no Docker/PostgreSQL here)

- **Backend: 606 passed, 6 skipped** (the 6 skips are PostgreSQL/Redis-only). 22 new tests
  in `apps/imports/tests/test_imports.py`:
  - templates and download;
  - format, encoding and mapping detection with encrypted storage and audit;
  - Windows-1252 and XLSX;
  - 4 bad files; row limit, zip bomb and macro;
  - formula detection; mapping validation;
  - **A13**: 100 assets with 5 duplicates → 95 create / 5 conflict, commit, report, safe
    re-import;
  - **A23**: monitor/TV with no IP or serial;
  - review-only serial/name matches;
  - update by id/tag with lock, category and duplicate checks;
  - formulas and custom fields;
  - site scope and permissions;
  - commit rules: preview first, 428 without key, re-planning, duplicate key;
  - rollback of untouched rows only; missing rows never archive;
  - location, group and membership families; purged originals; other users cannot see
    jobs.
- Ruff check and format are clean; no migration drift; the OpenAPI schema validates with
  `--fail-on-warn` and matches the committed file.
- Frontend: typecheck, oxlint, **122 tests** (6 new) and the build all pass.
- First CI run 41797061711 on `424e924` **failed** on PostgreSQL. Membership rows store
  `<group id>:<asset id>` (73 characters) in `ImportRow.target_id`, which was 40
  characters wide. SQLite does not enforce lengths, so the workstation run passed. The
  failed check also left the job in "previewing".
  - Fix: widen the column to 100 (`imports.0002_widen_row_target`), and any unexpected
    preview failure now returns the job to "uploaded" with a message.
  - Regression tests added for both; backend now 606 passed locally.
- GitHub CI run 41797570026 on `ccddf26` (PostgreSQL 16 + Redis 7): backend **612 passed,
  0 skipped**; migrations applied and reversed (including `imports`); OpenAPI drift check;
  frontend 122 tests; Compose config and production image builds pass.
- Not run: Docker stack, Playwright, browser review at 1440×900 and 390×844.

**Open:**
- Retention period pending DEC-15.
- Limits to be confirmed by load tests (Task 022).
- Remaining families come with Tasks 015 to 017.
- Earlier open items: DEC-15, DEC-16 and DEC-17; regional Defender hosts; whether excess
  roles should block syncs; phone and tablet categories; ASM-46 severities; group
  re-evaluation on asset change.
