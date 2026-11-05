# Task 021 — Scoped reports and private digests

DEV baseline: ded41a1. Implementation and CI result recorded below.

## Delivered

Four report views share backend queries with CSV/XLSX/JSON encrypted exports:
inventory by site/category/vendor/owner, lifecycle by hardware/OS/firmware,
recorded Endpoint Central/Defender coverage and group replacement/ownership.
Site/group/search filters and paged results preserve current asset access. Missing
lifecycle assessments remain Unknown; evidence IDs are retained in exports. Coverage
distinguishes active, stale/disabled and absent links without inferring compliance
or agent eligibility. Group counts include only visible live members.

Export downloads bind to current creator permissions/site grants and active status.
Changed authorization or legacy artifacts without fingerprints require regeneration.
Personal owner fields follow existing masking. No new file transport or encryption.

Private daily/weekly UTC digests save validated filters and email only an authenticated
link to the owner's account address. Existing SMTP, templates, audit, outbox retries
and Celery are reused. Dispatch deduplicates schedule/slot; disabled SMTP queues
nothing. Delivery checks current owner, email, password state, permissions and schedule
version. Stale messages cancel; modified slots are not reissued. UI supports creating,
opening and enabling/disabling schedules; versioned API supports edits.

## Files and migration compatibility

New `backend/apps/reports/` contains models, migration, services, views, digest task
and regression tests. Accounts seeds two permissions; notifications seeds the generic
link template. Exports adds a nullable authorization fingerprint, protecting legacy
artifacts without breaking old-worker inserts. Apply migrations before new processes;
drain old workers before enabling new report families. Revert application code before
schema rollback; no asset/data contraction is part of this task.

Frontend adds the Reports route/navigation, typed client, filters/search, scoped tables,
export and schedule dialogs plus tests; existing navy UI tokens/components are reused.
The browser review covers existing application pages plus all four report views and
both dialogs at desktop/mobile widths. OpenAPI/types are regenerated. Backups include
report tables; the real restore fixture contains a saved disabled schedule. CI reverses
and reapplies the new app migration alongside existing gates. Docs/10, /11 and ASM-62
record notification, report, authorization and rollout semantics.

## Verification

Local full backend before the final two regressions: **818 passed, 7 skipped**
(PostgreSQL/Redis/transport-dependent checks unavailable locally). Final focused report
suite: **9 passed**, including all formats, revocation, Unknown, private/versioned
schedules, disabled SMTP/dedup, weekly slots and recorded-link gaps. Existing export
suite passed **26 tests**. Full frontend: **206 passed**; final focused frontend:
**5 passed**, and lint/typecheck/build passed. Ruff check/format,
migration drift and OpenAPI validation passed. Synthetic Edge browser review produced
**53 screenshots**, with no browser errors or unmapped API requests; representative
desktop lifecycle, mobile coverage and mobile digest dialog were visually inspected.

CI: pending push. PostgreSQL/Redis, migration reversal/reapply, schema drift, Compose,
production images and real encrypted SFTP/isolated restore must pass before completion.

## Limits and next action

No live vendor/SMTP access or production commissioning. Legacy exports need regeneration.
Current reports do not add a BI designer, arbitrary recipients, attachments, full
software-license compliance or new identity policy. Downloaded copies cannot be revoked.
No scale/throughput guarantee is inferred from functional fixtures. Existing operator
deployment, identity, relay and DEC-09 backup/restore gates remain open.

Next: finish CI and record its result; Task 022 pilot needs approved target-host inputs.
