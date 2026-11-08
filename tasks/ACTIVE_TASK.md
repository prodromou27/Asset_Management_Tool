# Current task: 022h | Runtime source/compiler applicability review (complete)

Owner continuation 2026-11-08. Baseline 7f86cf3; preserve optional local MFA and the
approved UI. Read: AGENTS.md, docs/00, docs/14 and docs/17; prior evidence in
TASK022F2_REPORT.md, TASK022F3_REPORT.md and TASK022G1_REPORT.md.

Outcome: reviewed exact retained image artifact 13615495768 from green CI
42474781375 (runtime source 0b21447); SHA-256 verified before bounded in-memory JSON
inspection. Only docs changed between that source and the review baseline.
- API/backup include SQLite 3.53.4-r0; matching vendor recipe enables FTS5.
  No application SQLite/FTS5 request path found, but upstream patch/provenance and
  linked runtime flags remain unverified. Keep held, not blanket-exempt.
- Backup restic 0.18.1-r9 logs Go 1.26.9; no gobinary/module/stdlib result is present.
  Approved SFTP/OpenSSH path narrows X.509 exposure, not all Go/restic applicability.
- PostgreSQL gosu's pinned module and Go 1.27.3 result are present. Prior compiler
  coverage gap is resolved for this retained build, without a permanent exemption.

Evidence/dispositions: TASK022H_REPORT.md; docs/17 ASM-74; ops/security/README.md
explicitly records the manual release hold. G02 remains held despite green automated
vendor scans. No source/runtime/image, dependency, schema, UI or gate change.
Checks: artifact hash/JSON, targeted source/config and primary-source review,
git diff --check. No target code/PoC/build/test or live service was run. Prior green
902+902 backend /224 frontend CI is referenced, not claimed as rerun for this review.

Next bounded task: 022h1, exact-image upstream Go coverage and patched SQLite proof,
following TASK022H_REPORT.md acceptance. Require restic/gosu module+stdlib coverage,
preserve raw vendor and upstream findings, verify library version/flags/patches and
retain PostgreSQL/Redis/SFTP, restore, Nginx and strict image regression gates.
Use controlled isolated Linux execution; local Docker is unavailable here.
Do not waive findings, remove required libraries blindly, deploy, touch existing
volumes or silently start another epic. Host/TLS/recovery/key custody, live sources/
SMTP/backup commissioning and G6 remain separate open gates.
