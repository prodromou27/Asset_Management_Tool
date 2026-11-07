# Task 022f - dependency and image vulnerability evidence

Owner continuation: 7 November 2026. Baseline f88cc18. Addresses G02's missing scan
evidence; no production host, live connector, network scan or registry publication.

Added a checksum-pinned Trivy installer and static scan/gate under ops/security.
Lock mode scans only staged uv/pnpm metadata with development dependencies; image
mode scans saved archives for API/worker/scheduler, backup runner, frontend, proxy,
PostgreSQL and Redis. No app containers run. Exact source/lock/image identity,
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
is available locally. CI scan results and any required remediation remain pending.

Limits: vulnerability DB coverage and current platform/build only; not secret/history,
license, malicious-code or full security auditing. Image tags are build inputs; actual
deployment must pin/promote scanned digests and rescan changed builds. MFA (G04), host
commissioning (G05), G6 and any unremediated scan findings remain release gates.
