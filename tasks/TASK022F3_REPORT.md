# Task 022f3 - API/backup image CI remediation

Owner reported CI failure on 7 November 2026. Baseline `c656e17`. The failed step in
CI 42384258801 was the image advisory gate: API 47 HIGH; backup 1 CRITICAL/52 HIGH.
All application, browser, dependency, load and isolated runtime/restore checks passed.
This task addresses the remaining image inputs without weakening the gate.
Code paths: `backend/Dockerfile`, `.github/workflows/ci.yaml` and
`ops/security/check_backend.py`; deployment rationale is ASM-71 in docs/17.

ASM-71 changes only the production Python container OS from Debian to official,
digest-pinned Python 3.12.16 Alpine 3.24. The uv lock is unchanged; installation uses
musllinux wheels and refuses source builds. UID/GID are explicit 10001, avoiding
Alpine's reserved GID 999; host secret-mount permissions need commissioning. Backup tools
remain restricted to backup-runner: supported stable Alpine PostgreSQL 16 client,
restic and OpenSSH client packages. Alpine's OpenSSH backport includes the critical
client fix identified in Task 022f2. No application schema, host or data migration.

glibc-to-musl compatibility requires additional proof: a CI-only target extends the
real backup runtime with the existing locked test dependencies. The harness starts
new PostgreSQL/Redis/SFTP containers on an internal-only network, with no host ports,
live accounts, existing volumes or Docker socket. It generates credentials/host keys,
streams only client key files into the nonroot client's temporary directory, mounts
only specific cross-repository test sources and sanitized fixtures read-only, and
runs the backend suite against real PostgreSQL/Redis and the pinned SFTP fixture. That suite
includes encrypted backup/restore plus incorrect-password/host-pin rejection.
Cleanup targets only its generated resource names and temporary directories.

The ordinary host-based backend/browser/load checks, production imports/deploy check,
Redis recovery, encrypted fixture recovery and strict six-image scan also remain.
Test dependencies are excluded from both release targets. Windows local checks cannot
prove Linux ABI compatibility; CI is required for the candidate proof.

Local verification: 12 scanner/gate tests, Ruff, workflow YAML parsing and diff checks
passed. **All six CI jobs passed** in
[CI 42397841169](https://github.com/prodromou27/Asset_Management_Tool/actions/runs/42397841169)
for `0bf2051`. The first candidate exposed Alpine's reserved GID 999; selecting
explicit unreserved UID/GID 10001 corrects that build failure.
The initial container test attempt also identified the root fixture data paths;
the harness now explicitly mounts the six sanitized connector/discovery JSON files.

Final evidence: **853 tests pass in the ordinary backend job and another 853 pass
inside the candidate runtime**, with no skips reported. The candidate suite exercises
PostgreSQL 16.15, Redis and the pinned SFTP encrypted backup/restore path, including
wrong-password/host-pin rejection. **217 frontend tests**, API/schema parity,
lint/type/build, browser/CSP, reference load, production imports/deploy checks,
Redis AOF/RDB recovery and the separate isolated restore all pass.

| Image | Before CRITICAL / HIGH | Final CRITICAL / HIGH | Final gate |
| --- | --- | --- | --- |
| API / worker / scheduler | 0 / 47 | 0 / 0 | Passed |
| Backup worker | 1 / 52 | 0 / 0 | Passed |
| Frontend | 0 / 0 | 0 / 0 | Passed |
| Nginx proxy | 0 / 0 | 0 / 0 | Passed |
| PostgreSQL | 0 / 0 | 0 / 0 | Passed |
| Redis | 0 / 0 | 0 / 0 | Passed |

The strict scan reports **zero evidence errors**, all six targets, supported OS
versions and no HIGH/CRITICAL findings. Both lock scans pass. API/backup each retain
7 LOW/8 MEDIUM findings; the other four images each retain one MEDIUM and PostgreSQL
also retains one UNKNOWN. These remain visible; passing is not vulnerability-free.

Reviewed image artifact **13583968945**, SHA-256
`d98bdede87a30dd397c4a03ce8bb86d61ccc0db84b652d6e40cc9496412b149a`;
restore artifact **13584318171**, SHA-256
`00efaa66ce108f7783bd3826bf2d6dcd920d07b294a267902ce6cdcf90830683`.
Both hashes were verified before parsing JSON in memory, without archive path
extraction. Image evidence records source `0bf2051f06f636f1b849bed1b54adf287171548c`,
Trivy 0.76.2 and DB update `2026-11-07T12:52:01.765289267Z`. Restore records passed
checks, PostgreSQL 16.15, network isolation and temporary-target removal.

Limits: vendor advisory coverage differs by distribution. Retain the Task 022f2
source/applicability review (including SQLite); a clean vendor scan does not establish
that all upstream advisories are absent or unreachable. The build reports packaged
restic 0.18.1 compiled with Go 1.26.9; this scan reports it through OS package coverage,
without a separate Go-binary result. Compiler/module applicability review therefore
remains open alongside SQLite/source review. No waiver or full security
sign-off is introduced. Host capacity, identity/MFA, live-source/SMTP/backup destination
commissioning and G6 remain open. Rollback is an isolated image/source revert with
the same application data format; old vulnerable images are not approved production
fallbacks. No deployment or existing-volume change is performed.

Outcome: the reported CI failure is resolved without ignored findings, threshold
relaxation, skipped jobs or test bypasses. Next: 022g MFA, retaining the separate
manual G02 review and commissioning/sign-off gates above.

Sources: [official Python Alpine build](https://github.com/docker-library/python/tree/master/3.12/alpine3.24),
[Alpine security data](https://secdb.alpinelinux.org/v3.24/main.json).
