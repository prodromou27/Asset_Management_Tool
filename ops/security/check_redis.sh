#!/usr/bin/env bash
# Disposable synthetic persistence proof, with no network or published ports.
set -euo pipefail
name="itam-redis-proof-$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
volume="$name-data"
created=false
cleanup() {
    status=$?
    if test "$status" -ne 0; then
        # Synthetic fixture only: no application configuration or credentials.
        docker inspect --format '{{json .State}}' "$name" >&2 || true
        docker logs --tail 80 "$name" >&2 || true
    fi
    docker rm --force "$name" >/dev/null 2>&1 || true
    if "$created"; then docker volume rm "$volume" >/dev/null; fi
    return "$status"
}
trap cleanup EXIT
docker volume create --label itam.runtime-proof=true "$volume" >/dev/null
created=true
docker run --detach --name "$name" --network none --read-only \
    --security-opt no-new-privileges:true --memory 128m --pids-limit 64 \
    --mount "type=volume,source=$volume,target=/data" \
    itam-redis:7.4.12 redis-server --appendonly yes --appendfsync always >/dev/null
ready() {
    for _ in {1..30}; do
        if test "$(docker exec "$name" redis-cli ping 2>/dev/null || true)" = PONG; then return; fi
        sleep 1
    done
    return 1
}
ready
test "$(docker exec "$name" sh -c 'awk "/^Uid:/ {print \$2}" /proc/1/status')" = 999
test "$(docker exec "$name" redis-cli SET itam-proof synthetic)" = OK
test "$(docker exec "$name" redis-cli SAVE)" = OK
docker restart "$name" >/dev/null
ready
test "$(docker exec "$name" redis-cli GET itam-proof)" = synthetic
# Also exercise the RDB path independently of AOF replay.
docker rm --force "$name" >/dev/null
docker run --detach --name "$name" --network none --read-only \
    --security-opt no-new-privileges:true --memory 128m --pids-limit 64 \
    --mount "type=volume,source=$volume,target=/data" \
    itam-redis:7.4.12 redis-server --appendonly no >/dev/null
ready
test "$(docker exec "$name" redis-cli GET itam-proof)" = synthetic
echo 'Redis nonroot startup, AOF restart and RDB recovery passed (network disabled).'
