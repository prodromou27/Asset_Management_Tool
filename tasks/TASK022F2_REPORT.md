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

Verification: 11 local scanner/gate tests and five focused restore tests passed;
Ruff and YAML parsing passed. Linux runtime/restore/new scan evidence is pending in
[CI 42382643999](https://github.com/prodromou27/Asset_Management_Tool/actions/runs/42382643999)
for `6b31d01`. New Redis proof checks UID 999, AOF restart and independent RDB recovery
with networking disabled and uniquely owned disposable resources. Restore CLI retains
its historical default and accepts an operator-selected image; CI selects the actual
production PostgreSQL build. This image argument is not exposed through an API.

Remaining Debian package triage, based on the preceding artifact and vendor status
checked on 7 November 2026 (counts to be replaced by fresh evidence):

| Source package | Prior HIGH/CRITICAL instances per affected image | Disposition |
| --- | --- | --- |
| zlib | 2 HIGH, API and backup | Available security fix applied; fresh scan required. |
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

G02/release remain held pending fresh results and remaining package remediation.
MFA, host commissioning and G6 remain separate open gates; no deployment authorized.
