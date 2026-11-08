# Locked dependencies and production-image vulnerability gate

**Manual release hold (022h, 2026-11-08):** a passing vendor image scan does not close
G02. Retained evidence still has SQLite 3.53.4-r0 in API/backup and lacks the APK-owned
restic binary's Go module/stdlib result. PostgreSQL gosu's Go coverage is present.
See [Task 022h dispositions and next proof](../../tasks/TASK022H_REPORT.md).
Until patched-library provenance and exact-binary compiler/module coverage are
validated, do not promote these images as security-signed-off builds. This is a
manual release hold, not an added automated gate or a suppression of findings.

The scanner reads static artifacts and runs a bounded SQLite identity/compatibility
probe on API/backup images. It does not scan networks, send application source to
a hosted scanner or add an application feature.
Runtime-base changes have a separate bounded, network-disabled Django import/deploy
check using synthetic CI configuration; it does not start an application service.
CI downloads the pinned Trivy 0.76.2 Linux/x86-64 release and verifies its hard-coded
SHA-256 before extracting only the binary. The pin/digest were checked against the
official immutable release assets on 7 November 2026. This is checksum verification,
not a claim that release signatures or build provenance were independently verified.

```bash
bash ops/security/install_trivy.sh /tmp/itam-security-tools
export TRIVY_BIN=/tmp/itam-security-tools/trivy
python3 -m unittest discover -s ops/security -p 'test_*.py' -v
python3 ops/security/scan.py locks
# On an isolated Docker builder after production image/restore checks:
python3 ops/security/scan.py images
```

The scanner expects committed tracked source and records its exact commit. Lockfile
mode stages only uv.lock/pyproject.toml and pnpm-lock.yaml/package.json, including
development dependencies. Coverage checks require both parsers and representative
runtime/dev/transitive packages. It does not install or execute those dependencies.
The scanner config/ignore files are explicitly disabled; all severities and unfixed
findings remain in JSON. Dependency lookup is offline after a fresh public advisory DB
download. Scanner version and database update/download metadata are recorded; a DB
older than 48 hours, future/missing timestamp or missing scan evidence fails closed.

Image mode reads production Compose build contexts, Dockerfiles and stages for API
(also worker/scheduler), backup-runner, frontend, PostgreSQL and Redis, and builds
them from the same cached inputs used by the preceding compatibility checks. External
images such as the official proxy are pulled using their configured references.
The rendered configuration enables the `backups` profile so the optional backup
worker is always included in release evidence.
Production PostgreSQL/Redis runtime maintenance is described in `infra/runtime/README.md`.
No rendered Compose secrets
or full image environment/history are written to evidence. It saves each exact local
image ID to a temporary archive and scans that archive without running it. Source
reference, image ID, registry digests when available, architecture and OS are recorded.
Only the task scratch directory is removed; application containers/volumes are untouched.

HIGH/CRITICAL findings, including those without fixes, block the gate. End-of-support
image OS versions also block it. Missing OS or installed Python-package coverage is
an evidence error. LOW/MEDIUM/UNKNOWN findings stay visible for review. There are no
automatic waivers, ignored-unfixed rules or blanket suppressions. Scanner/DB failures
cannot produce a clean result. Every target is attempted so a held target does not
hide the rest. `passed` means the configured threshold passed, not zero vulnerabilities.

Ignored reports live in `ops/security/results/{locks,images}/`. CI retains only root
JSON reports/summary for 14 days, not scanner caches or image archives. Always inspect
summary status, errors, counts, source/lock hashes and image identities together. A
nonzero command result holds release even when the ordinary test jobs are green.
Advisories require source/runtime triage; scanner severity is not proof of an exploit.

Task 022h1 keeps vendor reports and adds `backup-worker-upstream.json` and
`postgres-upstream.json` with comprehensive library detection against the exact same
saved image archive. The gate requires the expected restic/gosu path, its main module
and a versioned Go stdlib in that binary. Missing/development/ambiguous compiler or
module evidence fails closed. HIGH/CRITICAL in either report holds the target; the
vendor and upstream counts remain separate to avoid pretending duplicates are unique.
No upstream report replaces vendor backport evidence.

API/backup must report reviewed `sqlite-libs=3.54.1-r0`. Each exact image also runs
`runtime/check_sqlite.py` as its nonroot user in a read-only, network-disabled
container with an empty allowlisted environment, scratch tmpfs only, no capabilities,
one CPU, 256 MB, 32 processes, file-size and 30-second time limits. It checks the
actual Python-linked version, source ID, required compile options, loaded-library
hash and a small in-memory FTS5 negative-rowid/prefix fixture. Parent code binds the
JSON proof to the inspected image ID/source commit and reviewed manifest/recipe hash.
Only the generated proof container can be cleaned up. No database volume is mounted.
Raw proof files are retained as `{api,backup-worker}-sqlite.json`.

Image version tags remain build inputs; the report binds the scan to resolved IDs.
Release promotion must retain/publish those tested builds, pin deployment digests and
rescan after rebuilding or refreshing tags. A later rebuild of the same tag is not the
same evidence. No registry publication or host deployment is authorized/performed here.
Branch protection and scheduled rescans remain operator/repository policy decisions.

References: [Trivy release](https://github.com/aquasecurity/trivy/releases/tag/v0.76.2),
[uv coverage](https://trivy.dev/docs/latest/coverage/language/python/),
[pnpm coverage](https://trivy.dev/docs/latest/coverage/language/nodejs/).
