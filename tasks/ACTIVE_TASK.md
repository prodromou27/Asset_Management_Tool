# Current Task: 013 | CSV/XLSX imports with preview/guarded upsert

Status: **Complete (workstation-verified; CI pending at the time of writing)**
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
- Not run: Docker stack, Playwright, browser review at 1440×900 and 390×844.

**Open:**
- Retention period pending DEC-15.
- Limits to be confirmed by load tests (Task 022).
- Remaining families come with Tasks 015 to 017.
- Earlier open items: DEC-15, DEC-16 and DEC-17; regional Defender hosts; whether excess
  roles should block syncs; phone and tablet categories; ASM-46 severities; group
  re-evaluation on asset change.

Proposed next task: **014 | CSV/XLSX/JSON exports with RBAC and async jobs**
(tasks/BACKLOG.md). Do not start automatically.
