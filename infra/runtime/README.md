# Production runtime images

Task 022h1 validated runtime: `backend/Dockerfile` builds upstream SQLite 3.54.1 into a normal
Alpine `sqlite-libs` APK (origin `sqlite`) using `backend/runtime/sqlite/APKBUILD`.
The official source archive is pinned with Docker SHA-256 and recipe SHA-512, derived
only after verifying SQLite's published SHA3-256. Compilation/package assembly is
network-disabled. The isolated builder generates its own temporary signing key;
only its library APK enters the runtime. Installation accepts that local APK without
network access; it does not add a new repository or trusted signing key. APK metadata
and old library files are upgraded normally, rather than shadowing an old package.
Legacy SONAME and FTS3/4/5, RTree/session options are retained. Compilers, keys and
headers do not enter the release image. Provenance JSON/recipe are retained in
`/usr/local/share/itam/`; the exact-image probe records actual linkage/options/hash.

The backup image builds restic 0.19.1 using the same pinned Go 1.27.3
toolchain as gosu, with CGO disabled, module checksum verification, symbols/build info
retained and compilation network-disabled after dependency download. Only the binary,
license and build metadata enter the backup image; the APK-owned old restic is no
longer installed. Source tag commit `6aa3a516ce654808a1f28f9fa21e9b7c8e6e90bf`
is checked explicitly. `backend/runtime/restic/dependencies.txt` pins security updates
within existing dependency major versions; public module checksums authenticate them.
Go's native VCS metadata retains the source revision and modified-build marker;
the CLI reports upstream `0.19.1`, while the main-module identity is `v0.19.1+dirty`.
Effective go.mod/go.sum and build info remain in
the image. No build-info rewriting hides the dependency changes.
SFTP/CLI/format behavior passed runtime and encrypted restore proofs in CI 42580535491;
future changes must retain those gates. Evidence: `tasks/TASK022H1_REPORT.md`.

Forward/rollback: no application schema or PostgreSQL major/layout changes. Prove
both API/backup Python imports and the full PostgreSQL/Redis/SFTP suite on Linux,
plus exact vendor/upstream image scans and isolated restores. Reverting source/images
in isolated staging preserves app/database formats, but previously vulnerable builds
are not approved production fallbacks. No host or existing volume is changed here.
This is a maintained source-built library/tool, not a claim of upstream binary provenance.

Task 022f3's API/backup Python runtime is defined in `backend/Dockerfile`: pinned
Python 3.12.16 on supported Alpine 3.24, unchanged lockfile, musllinux wheels and
explicit application UID/GID 10001. Only the backup target includes PostgreSQL 16
client tools, restic and the SSH client. The CI-only `runtime-tests` target adds
test dependencies to the same runtime; `ops/security/check_backend.py` runs the
existing PostgreSQL/Redis suite and encrypted SFTP roundtrip on a new internal-only
network. It uses generated host pins/credentials and removes only its own resources.
Neither release target includes the test dependencies. Commission host secret-file
permissions for the explicit app account; this task changes no existing host mount.

Task 022f2 keeps PostgreSQL 16.15 and Redis 7.4.12 and their data layouts, using
digest-pinned upstream images. Compose dev images are unchanged. Build from the
production Compose configuration; the normal installer builds enabled services.

The PostgreSQL stage replaces only gosu. The Go 1.27.3 stage builds upstream gosu
1.20 commit `29b939aa5bd4dc588af765b8248f6e39150d2565`, with CGO disabled and
Go's public module checksum database enabled. This avoids the old compiler's
findings in the upstream helper without altering database binaries or entrypoint.
Symbols remain available to Go vulnerability tools. Upstream's security policy
requires reachability analysis for compiler CVEs; our strict image gate remains
enforced, and rebuilding is not a claim that those findings were exploitable.

The Redis stage copies the pinned official Redis 7 binaries and entrypoint into
supported Alpine 3.24.4, installs its runtime libraries and packaged setpriv,
and retains UID 999/GID 1000, /data, command and volume behavior. It does not copy
the unsupported OS or its package database. Build checks execute both Redis tools
and verify privilege dropping. This is a maintained derived image: update its
source/base/compiler pins together with runtime proofs and fresh scans. New library
ABI or upstream entrypoint assumptions must be reviewed before updating the pins.

CI builds both production targets. `ops/security/check_redis.sh` uses a unique,
labelled disposable volume/container, no network/host ports and synthetic data;
it checks UID, write/read, AOF restart and RDB recovery with AOF disabled. Its trap
removes only those generated resources. The existing encrypted backup fixture is
restored into a new network-disabled production PostgreSQL container with tmpfs
storage through `ops/restore/drill.py --image itam-postgres:16.15`.
The image scanner then inspects saved exact-image archives and retains findings
and identities even when the gate is held. Linux CI supplies these runtime checks;
local Windows lint/unit checks alone cannot establish compatibility.
Application jobs retain their separate CI service images; these derived images
receive the isolated proofs above. Approved-host full-stack commissioning remains open.

No host or existing data volume is changed by this task. Forward deployment requires
staging/host commissioning and promotion of tested image digests. An isolated source/
image revert preserves the service major and data layout; old vulnerable images are
not approved production fallbacks. Never use volume deletion for an image rollback.

References: [gosu source](https://github.com/tianon/gosu/tree/29b939aa5bd4dc588af765b8248f6e39150d2565),
[gosu policy](https://github.com/tianon/gosu/security),
[Go releases](https://go.dev/dl/),
[upstream Redis build](https://github.com/docker-library/redis/tree/master/7.4/alpine),
[upstream PostgreSQL build](https://github.com/docker-library/postgres/tree/master/16/alpine3.24).
