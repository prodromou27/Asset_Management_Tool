# Current task: 022f2 | Runtime image remediation and triage

Owner requested continuation on 2026-11-07. Baseline 2b295db; CSP is complete
(TASK022E_REPORT.md). Address G02 from TASK022C_REPORT.md; preserve approved UI.
Read: AGENTS.md, docs/00, docs/12, docs/14, docs/15 and docs/17. No host deployment.

Bounded slice: pinned checksum-verified scanner; all-dev/runtime lockfile scans and
exact production image archive scans; fresh DB/source/image identity, fail-closed
coverage and HIGH/CRITICAL/EOSL gates. Fix reviewed dependencies within current stack.
No product scanner, host/network scans, live APIs, automatic waivers or deployment.

Acceptance: both lock parsers/dev sentinels and all six runtime images reported;
missing/stale evidence cannot pass; all findings retained; reviewed HIGH/CRITICAL
results remediate or explicitly hold release; API generation/tests/CI compatible.
Prior evidence: TASK022F_REPORT.md / CI 42379722339. Frontend/proxy pass;
API/backup/PostgreSQL findings and Redis EOSL hold G02/release.
Current slice: apply the Debian zlib security update; replace gosu's compiler runtime
without changing PostgreSQL 16 storage; rebase pinned Redis 7 binaries on supported
Alpine. Verify nonroot Redis AOF/RDB recovery, production-image PostgreSQL restore,
runtime imports and fresh exact-image scans. Preserve every gate and existing volume.
Status: bounded slice complete. CI 42384258801 / 1ab0b78 reports all six runtime
targets with zero evidence errors. PostgreSQL, Redis, frontend and proxy pass;
all OS versions are supported. API 0 CRITICAL/47 HIGH and backup 1/52 still hold
G02/release. Zlib's two HIGH findings are cleared in each Python image.
All functional checks pass: 853 backend, 217 frontend, browser/CSP/load, production
imports, Redis AOF/RDB recovery and production PostgreSQL restore. Local gate/scanner
tests: 12; focused restore tests: 6; Ruff/Bash/YAML checks pass.
Evidence and limits: TASK022F2_REPORT.md, ops/security/README.md,
infra/runtime/README.md. No host deployment or existing-volume change was performed.
Next: 022f3 API/backup runtime package remediation, before 022g MFA; retain the
required SFTP backup path and strict gate. Do not silently start another slice here.
G6 remains open; no risk acceptance or host deployment implied.
