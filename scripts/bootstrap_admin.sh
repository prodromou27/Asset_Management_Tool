#!/usr/bin/env bash
# One-off named System Admin bootstrap (first-run and second emergency admin).
# No default credentials: the password is prompted interactively inside the
# api container and never passed on the command line.
#
# Usage: scripts/bootstrap_admin.sh <dev|prod> <username> "<display name>" [email]

set -euo pipefail

ENVIRONMENT="${1:?Usage: $0 <dev|prod> <username> \"<display name>\" [email]}"
USERNAME="${2:?Username required}"
DISPLAY_NAME="${3:?Display name required}"
EMAIL="${4:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$SCRIPT_DIR/compose.sh" "$ENVIRONMENT" exec api python manage.py bootstrap_admin \
  --username "$USERNAME" \
  --display-name "$DISPLAY_NAME" \
  --email "$EMAIL"
