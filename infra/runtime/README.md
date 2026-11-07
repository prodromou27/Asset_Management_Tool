# Production PostgreSQL and Redis runtimes

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
