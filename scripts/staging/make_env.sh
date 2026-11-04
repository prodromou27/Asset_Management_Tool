#!/usr/bin/env bash
# Writes the repository-root .env for a STAGING host reached by IP (docs/12 section 9).
# Secrets are generated here, written with mode 600 and never printed. Integrations
# stay off. Refuses to overwrite an existing .env.
#
# Usage: scripts/staging/make_env.sh <ip> [short-name] [cert-dir]

set -euo pipefail

IP="${1:?Usage: $0 <ip> [short-name] [cert-dir]}"
NAME="${2:-}"
CERT_DIR="${3:-/etc/itam/tls}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

[[ "$IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || { echo "Not an IPv4 address: $IP" >&2; exit 1; }
[[ -e "$ENV_FILE" ]] && { echo "$ENV_FILE exists; not overwriting it." >&2; exit 1; }
command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 1; }

# The IP comes first: the api healthcheck uses the first allowed host.
HOSTS="$IP"
ORIGINS="https://$IP"
if [[ -n "$NAME" ]]; then
  HOSTS="$HOSTS,$NAME"
  ORIGINS="$ORIGINS,https://$NAME"
fi

secret_key() { openssl rand -base64 96 | tr -d '\n=+/' | cut -c1-80; }
fernet_key() { openssl rand 32 | base64 | tr '+/' '-_'; }

umask 077
cat > "$ENV_FILE" <<ENV
# STAGING .env generated $(date -Is) by scripts/staging/make_env.sh. Never commit it.
# Data on this host is disposable; integrations stay off (ITAM_ALLOW_LIVE_INTEGRATIONS).
ITAM_ENV=staging
ITAM_PUBLIC_URL=https://$IP
ITAM_ALLOWED_HOSTS=$HOSTS
CSRF_TRUSTED_ORIGINS=$ORIGINS
ITAM_TIMEZONE=Asia/Nicosia
ITAM_LOG_LEVEL=INFO

POSTGRES_DB=itam
POSTGRES_USER=itam
POSTGRES_PASSWORD=$(openssl rand -hex 32)
DJANGO_SECRET_KEY=$(secret_key)

ITAM_TLS_CERT_DIR=$CERT_DIR

ITAM_ALLOW_LIVE_INTEGRATIONS=false
ITAM_INTEGRATION_LIBRENMS_TOKEN=
ITAM_INTEGRATION_ENDPOINT_CENTRAL_KEY=
ITAM_INTEGRATION_INTUNE_CLIENT_SECRET=
ITAM_INTEGRATION_M365_CLIENT_SECRET=

ITAM_IMPORT_ENCRYPTION_KEY=$(fernet_key)
ITAM_IMPORT_RETENTION_DAYS=90
ENV
chmod 600 "$ENV_FILE"

echo "Wrote $ENV_FILE (mode 600) for $HOSTS; secrets generated and not displayed."
echo "Keep a protected copy: losing DJANGO_SECRET_KEY or ITAM_IMPORT_ENCRYPTION_KEY"
echo "invalidates sessions and makes retained import files unreadable."
