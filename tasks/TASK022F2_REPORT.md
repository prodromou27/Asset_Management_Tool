# Task 022f2 - runtime image remediation and triage

Owner continuation: 7 November 2026. Baseline `2b295db`; prior findings and evidence
are in TASK022F_REPORT.md. This slice changes build inputs and isolated CI proofs;
no host, existing volume, service major, application schema or UI change.

Remediation (ASM-70): install the available Debian zlib security update in the shared
Python runtime; rebuild pinned upstream gosu 1.20 with pinned Go 1.27.3 for PostgreSQL;
retain official Redis 7.4.12 binaries/entrypoint on supported Alpine 3.24.4 with its
required setpriv package. See infra/runtime/README.md for pins, maintenance and rollback.
The scan runner now honors Compose build definitions for every built service instead
of pulling upstream PostgreSQL/Redis images. No ignore list or threshold change.

Verification: 12 local scanner/gate tests and six focused restore tests passed;
Ruff, Bash syntax and YAML parsing passed. Final Linux evidence is in
[CI 42384258801](https://github.com/prodromou27/Asset_Management_Tool/actions/runs/42384258801)
for `1ab0b78`. All functional jobs passed: **853 backend tests**, **217 frontend tests**,
lint/type/API checks, browser/CSP, load, runtime imports and isolated restore.
The overall run fails only the image gate, with **all six targets reported and zero
evidence errors**. Both lock scans pass with zero advisories. New Redis proof checks
UID 999, AOF restart and independent RDB recovery
with networking disabled and uniquely owned disposable resources. Restore CLI retains
its historical default and accepts an operator-selected image; CI selects the actual
production PostgreSQL build, rejects an incompatible runtime major before copying
or restoring the dump, and records its version. This image argument is not exposed
through an API. A key written only after the manual RDB snapshot distinguishes
AOF recovery from snapshot recovery; automatic RDB saves are disabled in the fixture.

Initial isolated checks caught a missing helper and its path mismatch: the exact
pinned Redis entrypoint invokes `/usr/bin/setpriv`, while Alpine 3.24 packages it
under `/bin`. The derived image installs the package, provides the expected path
and checks that exact command during build. The upstream entrypoint is retained.
The helper's util-linux source fixes are tracked in [Alpine's security database](https://secdb.alpinelinux.org/v3.24/main.json);
package 2.42.3-r1 includes the relevant backport for CVE-2026-78408.

The scan integration initially omitted the optional backup service when rendering
Compose. Enabling its `backups` profile fixes coverage; a regression test checks the
profile selection. The final report includes the backup image, rather than accepting
the earlier incomplete scan. The release gate stayed closed throughout.

| Runtime | Before CRITICAL / HIGH | Final CRITICAL / HIGH | Final OS EOSL | Gate |
| --- | --- | --- | --- | --- |
| API / worker / scheduler | 0 / 49 | 0 / 47 | No | Held |
| Backup worker | 1 / 54 | 1 / 52 | No | Held |
| PostgreSQL | 1 / 25 | 0 / 0 | No | Passed |
| Redis | 0 / 0 (EOSL) | 0 / 0 | No | Passed |
| Frontend | 0 / 0 | 0 / 0 | No | Passed |
| Nginx proxy | 0 / 0 | 0 / 0 | No | Passed |

Counts are finding instances, not unique exploitable vulnerabilities. Each passing
image retains one MEDIUM; PostgreSQL also retains one UNKNOWN. All severities remain
in the raw evidence. Zlib's two HIGH findings are cleared in each Python image;
PostgreSQL's 1 CRITICAL/25 HIGH and Redis's unsupported-OS blocker are cleared.

Reviewed artifacts (SHA-256 verified before parsing; JSON read in memory, no archive
path extraction): image-security-evidence **13579276026**,
`7e93f9dd05b468b4b49058432f90ac145f7414a52235bd8f99107b65033ea900`;
backup-drill-report **13578972949**,
`cb16ed97f7cc5820407f75fc8894f62d3d554ffd5eb718ac31e275b72709d589`.
The image summary records source/image identities, Trivy 0.76.2 and advisory DB update
`2026-11-07T12:52:01.765289267Z`. Restore records PostgreSQL 16.15, passed checks,
network isolation and temporary-target removal (about seven seconds for this fixture).
Application jobs use separate CI service images; the derived images receive the
isolated runtime/persistence/restore proofs, not approved-host full-stack validation.

Remaining Debian package triage, confirmed against final image findings and vendor
status checked on 7 November 2026:

| Source package | Final HIGH/CRITICAL instances per affected image | Disposition |
| --- | --- | --- |
| zlib | 0, API and backup | Security fix applied and fresh scan confirms clearance. |
| util-linux | 36 HIGH, API and backup | Four advisories repeated across nine binary packages; stable distro fix absent. Keep held. |
| acl | 1 HIGH, API and backup | Upstream fix adds ABI; stable backport absent. Keep held. |
| ncurses | 4 HIGH, API and backup | Report concerns infocmp CLI; component reachability needs proof. Keep held. |
| sqlite3 | 3 HIGH, API and backup | Production database is PostgreSQL, but Python runtime includes SQLite; no blanket exemption. Keep held. |
| systemd | 2 HIGH, API and backup | Vendor describes systemd-homed; library package matches need reachability proof. Keep held. |
| perl | 1 HIGH, API and backup | Archive::Tar advisory mapped to source package; installed-file/reachability proof needed. Keep held. |
| openssh | 1 CRITICAL + 5 HIGH, backup only | SSH client is required by approved off-host SFTP backups. Stable fix absent for client advisory; server-only matches need triage. Keep held. |

The shared application runtime uses a nonroot account, read-only root filesystem and
dropped capabilities. These controls inform triage but do not clear the gate. Vendor
priority and scanner severity differ for several source-package matches; no automated
waiver or claim of non-exploitability follows. Mixing testing/unstable Debian packages
or deleting required SFTP tooling would introduce compatibility/functionality risk.

Vendor references: [zlib](https://security-tracker.debian.org/tracker/CVE-2026-76844),
[util-linux mount](https://security-tracker.debian.org/tracker/CVE-2026-76642),
[util-linux nsenter](https://security-tracker.debian.org/tracker/CVE-2026-78408),
[acl](https://security-tracker.debian.org/tracker/CVE-2026-54369),
[ncurses](https://security-tracker.debian.org/tracker/CVE-2025-69720),
[SQLite](https://security-tracker.debian.org/tracker/CVE-2026-119373),
[systemd](https://security-tracker.debian.org/tracker/CVE-2026-16742),
[Perl](https://security-tracker.debian.org/tracker/CVE-2026-9538),
[OpenSSH client](https://security-tracker.debian.org/tracker/CVE-2026-60002),
[OpenSSH server](https://security-tracker.debian.org/tracker/CVE-2026-106553).

This bounded remediation/triage slice is complete. **G02/release remain held** for
the remaining API/backup findings; backup's CRITICAL is openssh-client CVE-2026-60002.
Next: **022f3 - API/backup runtime package remediation**, before 022g MFA. Reassess
the minimal supported runtime/package strategy and prove backup SFTP compatibility;
do not waive findings, remove required backup tooling or mix unstable distro packages.
MFA, host commissioning and G6 remain separate open gates; no deployment authorized.
