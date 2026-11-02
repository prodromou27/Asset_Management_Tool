#!/usr/bin/env bash
# Wrapper that always pairs the base Compose file with exactly one environment
# override and the repository-root .env file.
#
# Usage: scripts/compose.sh <dev|prod> <docker compose args...>
# Example: scripts/compose.sh dev up -d --build

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <dev|prod> <docker compose args...>" >&2
  exit 1
fi

ENVIRONMENT="$1"
shift

case "$ENVIRONMENT" in
  dev|prod) ;;
  *)
    echo "Unknown environment '$ENVIRONMENT'. Expected 'dev' or 'prod'." >&2
    exit 1
    ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ITAM_ENV_FILE:-$REPO_ROOT/.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE (copy .env.example and fill in local values)" >&2
  exit 1
fi

exec docker compose \
  --env-file "$ENV_FILE" \
  -f "$REPO_ROOT/infra/compose.yaml" \
  -f "$REPO_ROOT/infra/compose.$ENVIRONMENT.yaml" \
  "$@"
