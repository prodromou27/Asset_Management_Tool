# Task 022f - dependency and image vulnerability evidence

Owner continuation: 7 November 2026. Baseline f88cc18. Addresses G02's missing scan
evidence; no production host, live connector, network scan or registry publication.

Added a checksum-pinned Trivy installer and static scan/gate under ops/security.
Lock mode scans only staged uv/pnpm metadata with development dependencies; image
mode scans saved archives for API/worker/scheduler, backup runner, frontend, proxy,
PostgreSQL and Redis. The scanner reads static archives. A separate migration smoke
process imports Django/drivers and runs deploy checks with networking disabled and
synthetic configuration. Exact source/lock/image identity,
scanner version and fresh DB timestamps accompany raw all-severity results.

Missing/invalid reports, missing package/OS coverage or stale database fail closed.
HIGH/CRITICAL (including unfixed) and end-of-support OS hold release. Lower severity
findings remain visible. No suppression file or automated waiver is introduced.
The ordinary test/restore gates run before image evaluation, and JSON evidence is
retained even when scans hold release. Read ops/security/README.md for commands/limits.

The initial frontend advisory audit found 18 dependency advisories, including 6 HIGH,
through the development-only openapi-typescript 6.7.6 -> Undici 5.29.0 chain. A scoped
override uses patched Undici 6.29.1 without changing the API generator or TS 7 choices.
The advisory audit now reports **zero** at every severity. Generated schema.d.ts is
unchanged; all **217 frontend tests**, lint, typecheck and build passed. Existing Vite
chunk-size advisory remains. These were package advisories, not demonstrated product
exploits. Primary examples: [Undici TLS advisory](https://github.com/advisories/GHSA-2m5v-pch6-74hx),
[Busboy advisory](https://github.com/advisories/GHSA-x8mw-p69m-v3mx).

Local gate checks: **8 unittest cases passed**, plus Ruff lint/format and workflow YAML
validation. Scanner/image execution is Linux CI evidence; no Docker/Trivy installation
is available locally. In [CI run 42378558061](https://github.com/prodromou27/Asset_Management_Tool/actions/runs/42378558061)
for `3cc100c`, Trivy 0.76.2 validated both lockfile parsers/development coverage and
reported zero advisories at all severities, with no evidence errors. Application
test jobs also passed. Production image results follow below.

Initial image evidence from that run: no scan/coverage errors, but release was held.
API: 2 CRITICAL/40 HIGH; backup: 3/46; frontend and proxy: 3/64 each; PostgreSQL: 1/25;
Redis: 0/0 with one MEDIUM. Frontend/proxy and Redis used end-of-support Alpine 3.21.
These are scanner finding instances, not unique exploitable application vulnerabilities.
Raw reports and identities are retained as image-security-evidence artifact 13576623355.

Reviewed remediation refreshes and digest-pins the Python 3.12 runtime/client-tool
OS and stable Nginx/Alpine base (ASM-69), with a network-disabled production-container
compatibility check. Existing source/old-image functional gates provide the baseline;
new images passed the functional gates described below. No host/data/volume change is performed.
PostgreSQL's Go findings originate in its bundled gosu binary; Redis still needs a
supported OS solution within the locked Redis major. These are held for further
remediation/triage, not suppressed or declared non-exploitable.

Refreshed evidence: [CI run 42379722339](https://github.com/prodromou27/Asset_Management_Tool/actions/runs/42379722339)
for `57345f7` completed both lock scans and all six image scans with **zero evidence
errors**. All functional jobs passed: 851 backend tests, 217 frontend tests, API parity,
lint/type checks, CSP/browser coverage, Nginx response checks, load and restore checks.
The new network-disabled runtime imports/deploy checks also passed. The overall run
is **failed intentionally by the image release gate**, not a scanner execution failure.

| Runtime | Initial CRITICAL / HIGH | Refreshed CRITICAL / HIGH | Refreshed OS EOSL | Gate |
| --- | --- | --- | --- | --- |
| API / worker / scheduler | 2 / 40 | 0 / 49 | No | Held |
| Backup worker | 3 / 46 | 1 / 54 | No | Held |
| Frontend | 3 / 64 | 0 / 0 | No | Passed |
| Nginx proxy | 3 / 64 | 0 / 0 | No | Passed |
| PostgreSQL | 1 / 25 | 1 / 25 | No | Held |
| Redis | 0 / 0 | 0 / 0 | Yes | Held |

Each passing Nginx-based image retains one MEDIUM finding. The base refresh removes
their HIGH/CRITICAL findings and unsupported OS, but does not uniformly reduce counts
across other images. Backup's remaining CRITICAL is reported against openssh-client
(`CVE-2026-60002`, no fixed version in this report). PostgreSQL's is against gosu's
Go stdlib v1.24.6 (`CVE-2025-68121`, fixed versions reported). API/backup OS package
findings and Redis's Alpine 3.21 EOSL still require remediation/triage. These labels
describe scanner evidence; runtime exploitability has not been established.

Refreshed raw reports, source/image identities and summary are retained as
`image-security-evidence`, artifact **13577261205**, SHA-256
`6c8f9644eb62a734cfb5b2818024b3a6b57877c19dd3c1ab25c6c29068534516`.
Artifact bytes were verified before local review. The bounded automation/initial
remediation slice is complete; **G02 and release remain held**. Next task is **022f2:
remaining runtime image remediation/triage**, before 022g MFA. No waiver, deployment
or production readiness is implied.

Limits: vulnerability DB coverage and current platform/build only; not secret/history,
license, malicious-code or full security auditing. Image tags are build inputs; actual
deployment must pin/promote scanned digests and rescan changed builds. MFA (G04), host
commissioning (G05), G6 and any unremediated scan findings remain release gates.
