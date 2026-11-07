# Current task: 022f | Static dependency/image vulnerability evidence

Owner requested continuation on 2026-11-07. Baseline f88cc18; CSP is complete
(TASK022E_REPORT.md). Address G02 from TASK022C_REPORT.md; preserve approved UI.
Read: AGENTS.md, docs/00, docs/12, docs/14, docs/15 and docs/17. No host deployment.

Bounded slice: pinned checksum-verified scanner; all-dev/runtime lockfile scans and
exact production image archive scans; fresh DB/source/image identity, fail-closed
coverage and HIGH/CRITICAL/EOSL gates. Fix reviewed dependencies within current stack.
No product scanner, host/network scans, live APIs, automatic waivers or deployment.

Acceptance: both lock parsers/dev sentinels and all six runtime images reported;
missing/stale evidence cannot pass; all findings retained; reviewed HIGH/CRITICAL
results remediate or explicitly hold release; API generation/tests/CI compatible.
Status: implemented; scoped Undici override cleared 18 frontend advisories (6 HIGH).
217 frontend tests, API type parity/types/build and 8 gate tests/Ruff passed. Actual
Linux scans and image findings pending CI. See TASK022F_REPORT.md / ops/security/README.md.
Next: review CI findings and finish this slice; then 022g identity/MFA gate. G6 remains
open; digest promotion, MFA and commissioning require their own evidence/decisions.
