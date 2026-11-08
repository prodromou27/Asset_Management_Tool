# Task 022h1 - SQLite remediation and compiler coverage

Owner continuation, 8 November 2026. Baseline `123bdf4`; findings in TASK022H_REPORT.md.
Candidate implementation: source-built SQLite 3.54.1 APK upgrade, unchanged restic
0.18.1 rebuilt with pinned Go 1.27.3, required exact-binary module/compiler evidence,
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

Paths: `backend/Dockerfile`, `backend/runtime/`, `ops/security/{scan,gate,test_*}.py`,
CI timeout and operator docs. No app migration/RBAC/API/UI changes are needed.
Rollback is isolated source/image reversal with unchanged PostgreSQL layout;
previous vulnerable images are not approved production fallbacks. Future updates
need maintained source/compiler/checksum pins and equivalent compatibility proof.

References: [SQLite source/hashes](https://sqlite.org/download.html),
[fixed SQLite release](https://sqlite.org/releaselog/3_54_0.html),
[restic source version](https://github.com/restic/restic/tree/v0.18.1),
[Go security releases](https://go.dev/doc/devel/release),
[Trivy upstream detection](https://trivy.dev/docs/latest/scanner/vulnerability/#detection-priority).
