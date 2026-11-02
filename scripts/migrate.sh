#!/usr/bin/env bash
# One-off schema migration. Run explicitly after postgres/redis are healthy;
# containers never migrate automatically on startup.
#
# Usage: scripts/migrate.sh <dev|prod>

set -euo pipefail

ENVIRONMENT="${1:?Usage: $0 <dev|prod>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$ENVIRONMENT" == "prod" && "${ITAM_CONFIRM_PROD_MIGRATION:-}" != "yes" ]]; then
  echo "Refusing to migrate prod without ITAM_CONFIRM_PROD_MIGRATION=yes" >&2
  echo "Take and verify a backup first (docs/12_DEPLOY_DOCKER_ALMALINUX.md)." >&2
  exit 1
fi

"$SCRIPT_DIR/compose.sh" "$ENVIRONMENT" run --rm --no-deps api python manage.py migrate --no-input
"$SCRIPT_DIR/compose.sh" "$ENVIRONMENT" run --rm --no-deps api python manage.py migrate --check
