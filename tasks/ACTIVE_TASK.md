# Current task: 022h1 | Complete — SQLite remediation and Go coverage

Completed 2026-11-09. Source `17f72dd08239ca870195d6e058a4e1dc9dc6749c`.
CI 42580535491: all six jobs passed; initial browser/scanner download HTTP 504s
cleared on failed-job retry. No skipped/reduced checks or security waivers.

Outcome: SQLite 3.54.1 replaces the old APK normally, preserving metadata, SONAME
and FTS options. Restic 0.19.1 uses explicit security dependency pins and Go 1.27.3;
native identity `v0.19.1+dirty` discloses the custom build. Scanner retains six vendor
reports plus comprehensive restic/gosu library reports, requires versioned exact-
binary coverage and isolated actual SQLite linkage proof. All reports have zero
HIGH/CRITICAL and zero evidence errors.

Proof: 18 scanner tests and Ruff/format; 902 native + 902 rebuilt-runtime backend
tests; 224 frontend; 14 browser scenarios; 136 CSP screenshots; 22 real Nginx
responses; PostgreSQL/Redis/SFTP, wrong-pin/password, deploy/import, Redis recovery
and isolated encrypted restore after source/storage removal. Retrieval+restore
9.771648 seconds. Image/restore artifact digests and identities: TASK022H1_REPORT.md.
Windows lacks Docker; Linux runtime proof ran in CI. No existing host/volume changed.

G02's SQLite/compiler coverage gap and discovered HIGH/CRITICAL findings are resolved.
Manual release sign-off remains open for retained UNKNOWN/lower-severity review,
plus host/TLS/recovery/key custody and live-source/SMTP/backup commissioning. Optional
local MFA, PostgreSQL formats, SFTP workflow and approved UI remain intact.

Next bounded task: 022h2 — review retained Go UNKNOWN records (GO-2026-5932 in restic,
CVE-2026-39824 in gosu) and lower pip/rustls/zlib findings. Establish exact package/
symbol applicability and approved-command exposure; record remediation or evidence-
based dispositions. No blanket exemption, threshold change or host deployment.
Read AGENTS.md, docs/00_MASTER_DECISIONS.md, docs/14_SECURITY_NFR.md,
docs/17_ADR_OPEN_DECISIONS.md, TASK022H_REPORT.md and TASK022H1_REPORT.md.
Do not silently start that task or another epic in this run.
