#!/usr/bin/env bash
# Builds and starts the production-mode stack on a STAGING host (docs/12 section 9).
# Steps: validate config -> inspect ports -> build -> postgres/redis -> migrate once ->
# start -> wait healthy -> check --deploy -> smoke test -> record. Stops at the first
# failure. Requires ITAM_CONFIRM_STAGING=yes because it migrates the database.
#
# Usage: sudo ITAM_CONFIRM_STAGING=yes scripts/staging/deploy.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE="$REPO_ROOT/scripts/compose.sh"
ENV_FILE="${ITAM_ENV_FILE:-$REPO_ROOT/.env}"
step() { printf '\n== %s\n' "$*"; }
die()  { echo "STOP: $*" >&2; exit 1; }
envval() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2-; }

[[ "${ITAM_CONFIRM_STAGING:-}" == "yes" ]] || die "set ITAM_CONFIRM_STAGING=yes (this host's data is disposable staging data)"
[[ -f "$ENV_FILE" ]] || die "missing $ENV_FILE (scripts/staging/make_env.sh)"
[[ "$(stat -c %a "$ENV_FILE")" == "600" ]] || die "$ENV_FILE must be mode 600"
[[ "$(envval ITAM_ENV)" != "production" ]] || die "this script is for staging; ITAM_ENV is production"
[[ "$(envval ITAM_ALLOW_LIVE_INTEGRATIONS)" == "false" ]] || die "keep ITAM_ALLOW_LIVE_INTEGRATIONS=false on staging"
CERT_DIR="$(envval ITAM_TLS_CERT_DIR)"
[[ -s "$CERT_DIR/fullchain.pem" && -s "$CERT_DIR/privkey.pem" ]] || die "no certificate in '$CERT_DIR' (scripts/staging/make_selfsigned_cert.sh)"
HOST="$(envval ITAM_ALLOWED_HOSTS | cut -d, -f1)"
REVISION="$(git -c safe.directory="$REPO_ROOT" -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"

step "SELinux labels for bind mounts (SELinux stays enforcing)"
if command -v selinuxenabled >/dev/null && selinuxenabled; then
  chcon -t container_file_t "$REPO_ROOT/infra/nginx/prod.conf"
  chcon -R -t container_file_t "$CERT_DIR"
  echo "labelled infra/nginx/prod.conf and $CERT_DIR as container_file_t"
fi

step "Validate Compose configuration"
"$COMPOSE" prod config --quiet
PUBLISHED="$("$COMPOSE" prod config --format json | python3 -c '
import json, sys
cfg = json.load(sys.stdin)
for name, svc in cfg["services"].items():
    for port in svc.get("ports", []):
        print(f"{name}:{port.get(\"published\")}")
')"
echo "published ports: ${PUBLISHED:-none}"
[[ "$PUBLISHED" == "nginx-proxy:443" ]] || die "only nginx-proxy:443 may be published"

step "Build images (revision $REVISION)"
"$COMPOSE" prod build --pull

step "Start PostgreSQL and Redis"
"$COMPOSE" prod up -d --wait postgres redis

step "Apply migrations once"
ITAM_CONFIRM_PROD_MIGRATION=yes "$REPO_ROOT/scripts/migrate.sh" prod

step "Start api, worker, scheduler, frontend and nginx-proxy"
"$COMPOSE" prod up -d --wait --wait-timeout 300
"$COMPOSE" prod ps

step "Django deployment checks"
"$COMPOSE" prod exec -T api python manage.py check --deploy --fail-level WARNING

step "Smoke test through the proxy"
BASE="https://$HOST"
# Trust only the staging certificate; resolve the allowed host to this machine.
CURL=(curl -sS --max-time 10 --cacert "$CERT_DIR/fullchain.pem" --resolve "$HOST:443:127.0.0.1")
"${CURL[@]}" -f "$BASE/api/v1/health/ready/" && echo
"${CURL[@]}" -f -o /dev/null -w 'frontend HTTP %{http_code}\n' "$BASE/"
CODE="$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$BASE/api/v1/assets/")"
[[ "$CODE" == "401" || "$CODE" == "403" ]] || die "unauthenticated /api/v1/assets/ returned $CODE (401/403 expected)"
echo "unauthenticated API HTTP $CODE (refused, as expected)"

step "Record"
mkdir -p "$REPO_ROOT/.deploy"
RECORD="$REPO_ROOT/.deploy/staging-$(date +%Y%m%d-%H%M%S).txt"
{
  echo "revision $REVISION deployed $(date -Is) host $HOST"
  docker compose version
  "$COMPOSE" prod images
  "$COMPOSE" prod ps --format '{{.Service}} {{.Status}}'
} > "$RECORD"
echo "Recorded in $RECORD"

cat <<NEXT

Staging stack is up at $BASE (temporary certificate: the browser will warn).
Next (docs/12 section 9): open 443/tcp in firewalld, then create the first admin with
  sudo scripts/bootstrap_admin.sh prod <username> "<Display Name>" [email]
NEXT
