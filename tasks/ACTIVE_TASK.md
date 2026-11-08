# Current task: 022h1 | SQLite remediation and Go coverage

Owner continuation 2026-11-08. Baseline 123bdf4; preserve optional local MFA, app DB
format, SFTP backups, approved UI and all security gates.
Read: AGENTS.md, docs/00, docs/14 and docs/17; TASK022H_REPORT.md acceptance applies.

Candidate: backend/Dockerfile and runtime source inputs build SQLite 3.54.1 as a
normal replacement APK, and unchanged restic 0.18.1 with pinned Go 1.27.3. No edge
repository, package shadowing, schema change or host deployment. Preserve metadata.
Scanner retains vendor scans plus separate comprehensive library scans; require
restic/gosu exact-path main-module and stdlib versions. Missing data fails closed;
HIGH/CRITICAL in either result holds the target. API/backup must show reviewed
SQLite metadata plus isolated actual-linkage/options/source/library-hash/FTS proof.

Status: 18 focused gate/scanner tests and Ruff/format pass locally. Published SQLite
SHA3-256 verified before deriving pinned SHA-256/SHA-512; no source was run locally.
Linux CI must prove source builds, actual linkage, full PostgreSQL/Redis/SFTP,
wrong-pin/password, deploy/import, Nginx, Redis recovery, restore and six image gates.
Compose job bounded to 30 minutes; SQLite probe is empty-env/nonroot/read-only,
network-disabled/scratch-only and resource/time bounded. Windows lacks local Docker.

Evidence/outcome: TASK022H1_REPORT.md (candidate pending). G02 remains held until
actual CI findings and exact-image/provenance results are reviewed.
Next: finish this candidate, remediate any new compiler/module findings, record
real outcome and next action. Do not waive findings, relax gates, deploy, change
existing volumes or silently start another epic. Host/TLS/recovery/key custody,
live-source/SMTP/backup commissioning and G6 remain separate.
