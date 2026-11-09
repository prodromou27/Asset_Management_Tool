# Task 022h1 - SQLite remediation and compiler coverage

Owner continuation, 8 November 2026. Baseline `123bdf4`; findings in TASK022H_REPORT.md.
Candidate implementation: source-built SQLite 3.54.1 APK upgrade, stable restic
0.19.1 with pinned Go 1.27.3 and security dependency updates, required exact-binary module/compiler evidence,
and an isolated actual-linked-library probe. No DB, UI, authentication or live host change.

Source inputs: SQLite official archive 3,332,984 bytes, publisher SHA3-256
`b6ced585c750916b1052667239a12c25a7ff34e7f06e1e6e01ecb0427657d9c4`,
verified before deriving Docker SHA-256
`926ef8d3eab93fbf6e06011901273eec076b25594a4e1cdadd50c987f4f6d64e`
and the recipe SHA-512. These are recorded in `backend/runtime/sqlite/source.json`.
Both archive download and source package assembly validate immutable checksums.
The temporary builder's package key stays in the builder; only its exact local APK
is accepted without network access in the release layer. Package name/origin and
legacy SONAME preserve consumers; old vulnerable files are replaced, not shadowed.

The restic Go stage uses the existing reviewed Go image pin, CGO disabled, bounded
build parallelism and public module checksum verification. Dependency downloads
precede network-disabled compilation; module version/build metadata and license
are retained. No stripping hides compiler/modules from the scanner. The backup
keeps the same command/SFTP workflow and must prove encrypted roundtrips/restore.

Scanner changes preserve the original six-image vendor reports. Backup/PostgreSQL
also get comprehensive library results with exact path, main-module and stdlib
coverage requirements. Missing/unversioned/development/ambiguous results fail;
HIGH/CRITICAL in either report holds the target. Counts stay separate because
vendor/upstream records can overlap. Both raw reports remain in the CI artifact.

API/backup require reviewed sqlite-libs metadata and a 30-second container proof:
nonroot, no network/volumes/capabilities, read-only root/toolchain, empty allowlisted
environment, scratch-only tmpfs, 1 CPU/256 MB/32 processes/file-size limit. It records
the actual Python-linked library/version/source ID/flags/hash and checks small
in-memory FTS5 prefix/negative-rowid behavior. Parent code matches source and recipe
provenance, then binds the result to exact image ID and source commit. Generated
containers are cleaned up on success/failure/timeout. No production DB is touched.

Local proof: **18 scanner/gate unit tests passed**, including missing compiler/module,
wrong binary, missing/stale SQLite metadata, HIGH despite complete coverage, and
probe isolation/timeout cleanup. Ruff/format pass. Linux candidate build, linkage,
runtime/restore and advisory proof remain required in CI; Windows has no local Docker.
The 30-minute Compose CI limit bounds the new source-build/runtime job.

G02 remains held while candidate validation is pending. Final source/CI/artifact
evidence, findings and dispositions will be recorded after the complete gates run.

CI [42519471978](https://github.com/prodromou27/Asset_Management_Tool/actions/runs/42519471978),
source `7812f7f8162f821f465e801cce93f6ce73d47614`, passed all functional gates:
902 native and 902 rebuilt-runtime backend tests, 224 frontend, 14 browser scenarios,
136 CSP screenshots, 22 Nginx response checks, Redis recovery and isolated encrypted
restore after source/storage removal (7.564447 seconds retrieval+restore). Both
SQLite probes passed at UID 10001 with FTS3/4/5/RTree/session options, source ID
`2026-10-16 14:45:20 555e07ef33f69a0957d24d8e555b702464a131d6f1607f4c3c1e4551e8e6ca76`,
library `/usr/lib/libsqlite3.so.3.54.1`; API library SHA-256
`23aba9d8edea4636952c4eb148c5188355746de50e4dbca3481c73d4c2173050`.
Scanner coverage was complete, with zero evidence errors. However restic 0.18.1's
dependencies had **1 CRITICAL/29 HIGH** in each vendor/upstream report (overlap,
not additive); all other images passed. Keep G02 held. Compiler is verified Go
1.27.3, demonstrating why compiler updates alone do not fix bundled modules.

Digest-verified image artifact `13633375965` SHA-256
`82b53de80be9544ff497da9d28925d1dc24460d47144aed86eef226e5bed4d5a`;
restore artifact `13632882189` SHA-256
`3c279436611790eb11f383367649f4bdc2d4e79dd70b3ae42b751e63cf12ed33`.
Reports were inspected as bounded JSON in memory without extraction/execution.

Remediation: stable restic 0.19.1 tag is explicitly checked against upstream commit
`6aa3a516ce654808a1f28f9fa21e9b7c8e6e90bf`. Its shipped module versions still leave
some findings, so `backend/runtime/restic/dependencies.txt` pins same-major updates
for go-jose, compress, x/crypto, x/net, x/text and grpc. Versions checked against
official Go proxy metadata on 8 November. SumDB verification remains enabled;
offline readonly-module compilation uses native Go VCS metadata (including the
modified marker) rather than synthesizing scan versions. CLI reports `0.19.1`;
the native main-module identity is `v0.19.1+dirty`. The
effective module/sum files and build info disclose the custom dependency build.
All SFTP, older-fixture restore and strict scan gates must pass again.

Candidate `8b4a9a3`, CI 42520724709, passed all six jobs and all six image gates,
including both comprehensive Go scans and both SQLite runtime proofs. HIGH and
CRITICAL counts are zero. Digest-verified artifact `13633716552` SHA-256
`b266ca2b68429d14d81d8ef59e3c72f47c8353823e3ef0b050dedc50c2170613`;
restore `13633204703` SHA-256
`1364c653fba747e5d754c58152263edf4b81e2352e590437c172abcc46a45ae4`
confirms recovery after source/storage removal in 6.898983 seconds. Evidence review
caught an ineffective legacy `main.version` linker override: upstream now exposes
a constant in internal/global. Remove the unused option and correct CLI documentation;
native VCS/main-module/compiler/dependency evidence was already correct.

Remaining UNKNOWN records stay visible: restic's GO-2026-5932 concerns the deprecated
`x/crypto/openpgp` package, not an assertion that all of x/crypto is unsafe. The app
invokes fixed backup/repository/SFTP commands, not restic self-update. This narrows
exposure but does not prove symbol absence or exempt future invocations. Keep its
record for focused package/symbol review; the default threshold is unchanged.
Gosu's retained x/sys CVE-2026-39824 and lower pip/rustls/zlib findings also remain
tracked. Automated threshold success is not complete security/release sign-off.

Initial candidate `2437d38`, CI 42515643237: all five non-image jobs passed; SQLite
compiled but abuild rejected uncompressed main-package man pages. The correction
uses normal Alpine static/doc/dev/libs splits (only libs enters the release),
without disabling postchecks. Coverage validation also rejects malformed version
labels; the probe explicitly selects UID/GID 10001 and the application interpreter.
Candidate 648fbbe then produced all subpackages but index creation rejected its
temporary signing key. Install that public key in the disposable builder only;
no signing key/trust store is copied into release targets. Rebuilt version smoke
checks are also network-disabled (e658530). These corrections retain validation.
The keygen install shortcut in 3bd8073 required absent `doas`; the root-only builder
now copies its newly generated public key directly, without adding a privilege helper.
Candidate 98be2b1 successfully built/installed SQLite and production images, then
the backup's offline `go install @version` attempted a deprecation metadata lookup
that GOPROXY=off forbids. Use Go's cached-download directory as a file-only proxy;
compilation remains network-disabled and module checksum checks remain enabled.
Candidate 4fe8c30 passed production image builds but offline restic compilation
needed an indirect module checksum absent from the lazy download. Prefetch and
verify the complete module graph with `go mod download all`; preserve SumDB and
the file-only proxy during compilation.
Candidate e000e61 confirmed that module-context download trusts upstream `go.sum`
without warming the separate SumDB lookup cache used by `go install @version`.
Download the selected dependency graph once outside that module as well, requiring
public checksum verification before offline installation. No verification is disabled.

Paths: `backend/Dockerfile`, `backend/runtime/`, `ops/security/{scan,gate,test_*}.py`,
CI timeout and operator docs. No app migration/RBAC/API/UI changes are needed.
Rollback is isolated source/image reversal with unchanged PostgreSQL layout;
previous vulnerable images are not approved production fallbacks. Future updates
need maintained source/compiler/checksum pins and equivalent compatibility proof.

References: [SQLite source/hashes](https://sqlite.org/download.html),
[fixed SQLite release](https://sqlite.org/releaselog/3_54_0.html),
[restic source version](https://github.com/restic/restic/tree/v0.18.1),
[stable update source](https://github.com/restic/restic/tree/v0.19.1),
[Go native VCS version metadata](https://go.dev/doc/go1.24),
[Go security releases](https://go.dev/doc/devel/release),
[Trivy upstream detection](https://trivy.dev/docs/latest/scanner/vulnerability/#detection-priority).
