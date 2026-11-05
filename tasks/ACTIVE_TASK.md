# Current Task: 020 | Admin settings, integration catalogue and health screens

Authorized by owner on 2026-11-05 after Task 019 completion. Work on DEV.
Task 019 outcome is preserved in TASK019_OUTCOME.md; latest baseline CI 42017098215 green.

Read: AGENTS.md, docs/00, 07 (tokens), 08 (integrations/administration), 09, 20;
docs/15 (relevant admin/security gates), docs/17 (existing deployment decisions).

Objective: fill missing administration workflows using existing modules and navy tokens.
- General organization/display settings: validated GET/PATCH, If-Match, permissions,
  before/after audit, clear preview and effective display preferences.
- Searchable provider catalogue alongside configured instances; accurately distinguish
  Planned/Beta/Available and configuration, never label unapproved sources healthy.
- Authenticated operational diagnostics: infrastructure, storage, integrations, SMTP,
  backups and durable job states, with actionable first-run checklist. Distinguish
  process readiness from production readiness; unknown/manual gates stay incomplete.
- Reuse existing users/sites/security/SMTP/backups/lifecycle pages. Present deployment-
  controlled settings as read-only; no invented controls or unsupported providers.

Acceptance: backend RBAC, validation/version conflicts and audit regression tests;
read-only diagnostics with no external vendor/SMTP probes or secret/host-path leakage;
frontend form/error/filter/permission states, schema sync, lint/typecheck/build;
real browser desktop/mobile checks; PostgreSQL/Redis and image/Compose CI.

Non-goals: live commissioning, production secret/destination changes, SSO/MFA architecture,
retention deletion, custom queue controls, Task 021. DEC-09 and other operator gates remain.

Status: complete. Implementation `79469ba`; CI run **42058286320** green.

Outcome: General settings API/UI, shared display preferences and organization branding;
searchable provider catalogue with URL-preserved tab; protected operational services,
integration/job evidence and actionable first-run checklist. Existing settings screens
remain in place. No live integration/SMTP/backup probes, secret changes or production
readiness approval. Added accounts.0014_generalsettings and 0015_admin_permissions.

Verification: full backend 810 passed / 7 environment skips (SQLite fallback), then
31 focused health/notification tests passed after reusing the SMTP health service;
full frontend 200 passed, then 22 focused settings/shell tests passed including the new
unsupported-timezone fallback. Typecheck, lint/build, schema validation and migration
drift passed. Browser review: 41 synthetic screenshots, no errors/unmapped calls/overflow.
Details and limitations: TASK020_REPORT.md. Task 019 history: TASK019_OUTCOME.md.

CI: **818 backend tests passed on PostgreSQL/Redis with no skips; 201 frontend tests
passed**. Migration drift/apply/reversal, OpenAPI/type drift, lint/format/typecheck/build,
production deploy settings, dev/prod Compose configuration, production and restricted
backup image builds and the real encrypted SFTP/network-isolated restore all passed.

Next: review Task 021 separately. Production commissioning/IdP/secret recovery and the
manual readiness gates remain pending operator decisions. Task 021 was not started.
