#!/usr/bin/env bash
# CI only: cached images, synthetic data, internal network, no published ports.
set -euo pipefail
cd "$(dirname "$0")/../.."
root_dir="$PWD"
fixture_dir="$(mktemp -d /tmp/itam-csp.XXXXXX)"
prefix="itam-csp-$RANDOM-$$"
network="$prefix-network"
cleanup() {
  for role in api frontend proxy-http proxy-https; do
    docker rm -f "$prefix-$role" >/dev/null 2>&1 || true
  done
  docker network rm "$network" >/dev/null 2>&1 || true
  docker image rm "$prefix-frontend" "$prefix-api-image" >/dev/null 2>&1 || true
  rm -f -- "$fixture_dir/fullchain.pem" "$fixture_dir/privkey.pem"
  rmdir -- "$fixture_dir" 2>/dev/null || true
}
trap cleanup EXIT
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=proxy-https \
  -addext subjectAltName=DNS:proxy-https -keyout "$fixture_dir/privkey.pem" \
  -out "$fixture_dir/fullchain.pem" >/dev/null 2>&1
docker build --pull=false -t "$prefix-frontend" frontend >/dev/null
docker build --pull=false --target production -t "$prefix-api-image" backend >/dev/null
docker network create --internal "$network" >/dev/null
limits=(--pull=never --network "$network" --read-only \
  --security-opt no-new-privileges:true --pids-limit 64 --memory 128m --cpus 1)
docker run -d "${limits[@]}" --cap-drop ALL --name "$prefix-api" --network-alias api --user 65534:65534 \
  -v "$root_dir/ops/csp/upstream.py:/fixture/upstream.py:ro" \
  "$prefix-api-image" python -B /fixture/upstream.py >/dev/null
docker run -d "${limits[@]}" --name "$prefix-frontend" --network-alias frontend \
  --tmpfs /var/cache/nginx --tmpfs /var/run --tmpfs /tmp "$prefix-frontend" >/dev/null
for mode in http https; do
  docker run -d "${limits[@]}" --name "$prefix-proxy-$mode" --network-alias "proxy-$mode" \
    --tmpfs /var/cache/nginx --tmpfs /var/run --tmpfs /tmp \
    -v "$root_dir/infra/nginx/$mode.conf:/etc/nginx/conf.d/default.conf:ro" \
    -v "$root_dir/frontend/content-security-policy.conf:/etc/nginx/snippets/content-security-policy.conf:ro" \
    -v "$fixture_dir:/etc/nginx/tls:ro" "$prefix-frontend" >/dev/null
done
docker run --rm "${limits[@]}" --cap-drop ALL --user 65534:65534 \
  -v "$root_dir/ops/csp/check_headers.py:/fixture/check_headers.py:ro" \
  -v "$root_dir/frontend/content-security-policy.conf:/fixture/policy.conf:ro" \
  -v "$fixture_dir/fullchain.pem:/fixture/ca.pem:ro" \
  "$prefix-api-image" python -B /fixture/check_headers.py
