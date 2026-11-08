# Task 022h - Runtime source/compiler applicability review

Reviewed 8 November 2026, baseline `7f86cf30eba33cd1ce592258091294864d2fe80c`.
Scope: SQLite in API/backup, restic's embedded Go compiler/modules, PostgreSQL gosu.
This completes the bounded evidence review. **G02 remains held**; this is neither
an exploit finding nor full vulnerability-free/release sign-off. No runtime change.

## Evidence identity

Reviewed [CI 42474781375](https://github.com/prodromou27/Asset_Management_Tool/actions/runs/42474781375),
source `0b214478b576e0eae9653c4b3097e791827dcba0`. Only documentation changed between
that revision and this review's baseline. Image artifact **13615495768**, SHA-256
`a398d94a2b653a9aebffb4cd51511a2d97bda696b2a61a94a69930d677342a45`,
was re-downloaded, hash-verified and parsed in memory without extracting image or
archive files. This is exact retained scan evidence, not a fresh rebuild/rescan.
Reports were produced by Trivy 0.76.2 with DB update
`2026-11-08T06:39:21.614725497Z` and identify Alpine 3.24.4.

The six-image gate passed its configured HIGH/CRITICAL threshold. Its coverage
does not resolve the component-level questions below. No waiver is introduced.

## Dispositions

| Component | Exact retained evidence | Source boundary and disposition |
| --- | --- | --- |
| SQLite, API and backup | Both reports list `sqlite-libs` / source `sqlite` **3.53.4-r0**. | **Keep held for patch/runtime validation.** Upstream fixes CVE-2026-119373 in 3.54.0. The matching Alpine stable recipe uses 3.53.4-r0, enables FTS5 and lists no additional source patch in its source inputs. The moving recipe is supporting evidence, not byte-for-byte provenance of the image's shared library. |
| restic, backup | OS package **0.18.1-r9**; job **128714366270** logs `restic 0.18.1 compiled with go1.26.9 on linux/amd64`. No `gobinary` result exists in this image report. | **Keep held for compiler/module coverage.** The package's presence and compiler string are established; its exact linked modules and upstream Go advisory coverage are not. No target vulnerability or non-applicability is inferred from an omitted result. |
| gosu, PostgreSQL | `gobinary` target `usr/local/bin/gosu`, module `github.com/tianon/gosu` **v0.0.0-20261025094355-29b939aa5bd4**, `stdlib` **v1.27.3**. | **Prior compiler-coverage gap resolved for this retained build.** Runtime Dockerfile pins the same upstream commit and Go 1.27.3 with CGO disabled. This result participates in the existing all-results severity gate. This is coverage evidence, not a permanent exemption or universal security claim. |

### SQLite reachability

The advisory requires attacker-influenced FTS5 `detail=none` rows with negative
row IDs followed by a prefix MATCH query. Upstream's fix changes allocation for
negative document IDs; it is not merely a CLI issue.

`backend/config/settings/base.py:136` selects PostgreSQL. The only Django SQLite
database selection found is the explicit local test fallback in
`backend/config/settings/test.py:15`, which refuses that fallback in CI. Targeted
source search found no application `sqlite3`, FTS5, extension-loading or FTS query
entry point. Backups explicitly reject non-PostgreSQL in
`backend/apps/backups/runner.py:131`. Asset search uses PostgreSQL, not SQLite FTS.

**Inference:** no application request-to-FTS5 exploitation path was established in
the reviewed source. That does not remove the installed library, prove its linked
build flags/patch bytes, or cover every bundled third-party runtime consumer.
Do not translate “PostgreSQL is used” into a blanket SQLite exemption. No exploit
was executed, and no application severity is assigned to this unresolved item.

### Go/restic reachability and scan behavior

`ops/security/scan.py` requests OS and library findings but does not select a
detection priority. Trivy documents `precise` as its default: OS-owned software
can rely on vendor advisories, omitting upstream language-level results. Its
`comprehensive` option enables broader upstream detection. This is a documented
mechanism consistent with the absent packaged-restic result; it still needs
verification on the pinned scanner and exact candidate binary.

`gate.py` requires OS/Python coverage but has no target-specific requirement for
restic Go modules/stdlib or gosu Go coverage. It evaluates all results that exist;
it cannot reject an omitted binary result solely from the current requirements.
The retained scan does identify gosu separately because it was copied into the
image rather than installed as an APK-managed binary.

The Go project records `crypto/x509` security fixes in 1.26.10 and 1.27.3.
Compiler string 1.26.9 therefore merits review, but alone does not establish the
presence/reachability of that package or absence of vendor backports.
`repository_env()` accepts only administrator-configured SFTP repositories, strips
unapproved restic environment options, and `transport_options()` forces an external
OpenSSH command with strict host-key pinning. The application's approved repository
path does not select restic's HTTPS backend. This narrows a possible X.509 path;
it does not justify exempting all Go, archive, filesystem or restic-module issues.

## Next bounded implementation: 022h1

1. Add a distinct exact-image upstream/compiler coverage proof using the pinned
   scanner's verified comprehensive mode or a pinned static Go-binary scanner.
   Keep raw reports alongside the existing vendor scan; do not replace vendor
   backport evidence with unreviewed upstream version guesses. Require restic
   module + stdlib and gosu module + stdlib coverage; missing data must fail closed.
2. Resolve SQLite with a supported patched package/base or a reproducible pinned
   backport/source build, preserving PostgreSQL as the application database.
   Do not remove `_sqlite3` or libraries blindly. Record exact source/patch hashes
   and linked library version/compile options on the candidate image.
3. Triage every new compiler/module finding against that binary and approved
   transport. If remediation is needed, rebuild with a reviewed compiler while
   preserving restic/SFTP behavior; no blanket CVE exclusions or threshold changes.
4. Prove the candidate on isolated Linux: no external network for target execution,
   empty allowlisted environment, read-only source/toolchain, scratch-only writes,
   bounded CPU/memory/process/output/time. Reuse functional PostgreSQL/Redis/SFTP,
   wrong-pin/password, import/deploy, Nginx, restore and six-image gates. Keep
   retained image identities and raw evidence. No host/volume/deployment action.

## Validation and limits

Performed: artifact SHA-256 verification and bounded JSON inspection, targeted source
and configuration review, official advisory/packaging/scanner-source checks, and
`git diff --check`. Existing green CI (902 backend tests in each runtime, 224 frontend
tests) is prior evidence, **not tests rerun for this review**.

No target code, PoC, library, binary, dependency installation or build was executed.
This Windows workspace has no available Docker-based isolated Linux execution
environment meeting the security-review skill's complete sandbox requirements.
Dynamic patch/build-flag and compiler/module validation is explicitly pending the
controlled candidate proof above. No live endpoint, tenant, SMTP or host was probed.

## Primary sources checked

- [SQLite upstream fix](https://github.com/sqlite/sqlite/commit/e1c9934f9f11a499029abb020ea715a08970da80),
  [Debian CVE record](https://security-tracker.debian.org/tracker/CVE-2026-119373),
  [Red Hat preconditions](https://access.redhat.com/security/cve/cve-2026-119373).
- [Alpine stable SQLite recipe](https://raw.githubusercontent.com/alpinelinux/aports/3.24-stable/main/sqlite/APKBUILD).
  Matching version/flags checked; a moving branch is not immutable build provenance.
- [Trivy detection behavior](https://trivy.dev/docs/latest/scanner/vulnerability/#detection-behavior),
  [pinned Go analyzer](https://raw.githubusercontent.com/aquasecurity/trivy/v0.76.2/pkg/fanal/analyzer/language/golang/binary/binary.go).
- [Go release security changes](https://go.dev/doc/devel/release),
  [pinned gosu entry point](https://raw.githubusercontent.com/tianon/gosu/29b939aa5bd4dc588af765b8248f6e39150d2565/main.go),
  [gosu security policy](https://github.com/tianon/gosu/security).
