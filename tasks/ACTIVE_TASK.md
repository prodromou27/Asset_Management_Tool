# Current task: 022f3 | Resolve API/backup image CI gate

Owner reported CI failure on 2026-11-07. Baseline c656e17; CSP is complete
(TASK022E_REPORT.md). Address G02 from TASK022C_REPORT.md; preserve approved UI.
Read: AGENTS.md, docs/00, docs/12, docs/14, docs/15 and docs/17. No host deployment.

Bounded slice: pinned official Python 3.12 Alpine runtime, frozen musl wheels,
stable PostgreSQL 16/restic/OpenSSH client packages, explicit app UID/GID 10001.
Validate the existing suite in that runtime against new internal-only PostgreSQL,
Redis and pinned SFTP fixtures; preserve the strict six-image vulnerability gate.
No product scanner, host/network scans, live APIs, waivers or deployment.

Status: complete. CI 42397841169 / 0bf2051: all six jobs pass. Both lock scans pass;
all six image targets pass HIGH/CRITICAL/EOSL thresholds with zero evidence errors.
853 tests pass in the ordinary backend job and another 853 in the candidate runtime;
217 frontend tests, browser/CSP/load, deploy checks and isolated restore pass.
The candidate suite verifies encrypted SFTP backup/restore and bad-password/pin
rejection. Local scanner tests: 12; Ruff/YAML/diff checks pass. No lockfile/schema/UI
changes or existing-volume/host deployment. Lower-severity findings remain visible.

Evidence: TASK022F3_REPORT.md, ops/security/README.md, infra/runtime/README.md.
Automated CI is green; vendor coverage is not full security sign-off. G02 source/
compiler applicability review (including SQLite and packaged restic/Go) remains open.
Next: 022g MFA; retain manual security review and host/live-service commissioning
as separate release gates. G6 remains open; no risk acceptance is implied.
