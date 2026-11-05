# Current task: 022a | Local pilot preparation and real API/browser rehearsal

Owner requested continuation and chose local preparation first (2026-11-05).
Baseline 4a6e64d. Task 021 and the approved UI/category navigation are complete.
Read: AGENTS.md, docs/00, docs/12-17 and docs/20. Do not deploy to a host.

Bounded slice: replace the unauthenticated E2E placeholder with an isolated, real
Django test-database + React/Playwright loopback rehearsal; synthetic accounts/data,
real login/CSRF, category filtering, asset registration, scoped group/report/export,
cross-site read/write refusal and disabled-session revocation. Reuse current services.
Add reproducible local/CI execution, an evidence matrix and staging handoff checklist.
No new dependencies, public listeners, vendor/SMTP calls or production migrations.

Acceptance: real backend/browser roundtrip and DB audit assertions, secret-free
summary, loopback network guard, test-only DB guard, lint/types/build and PostgreSQL
CI. SQLite can support local functional proof but cannot prove PostgreSQL scale.
Status: implemented and locally verified. Four pytest checks passed, including the
14-scenario real browser/API rehearsal; lint/types/build passed. TASK022A_REPORT.md
records proof and limits. Next: push DEV and verify PostgreSQL/Chromium CI, then
Task 022b reference-load measurements. Task 022 overall remains open for load/security/
UAT/recovery and AlmaLinux host gates; operator decisions remain required.
