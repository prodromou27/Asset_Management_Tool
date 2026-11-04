#!/usr/bin/env bash
# Switches an installed app from http:// to https:// (docs/12 section 9).
#
#   sudo bash scripts/enable_https.sh <fullchain.pem> <privkey.pem> [hostname]
#   sudo bash scripts/enable_https.sh --self-signed [hostname]
#
# fullchain.pem = server certificate followed by any intermediate certificates (PEM).
# hostname      = the name users will type (for example itam.example.local); it is added
#                 to the allowed hosts and becomes the public URL.
# --self-signed creates a temporary 1-year certificate (browsers will warn).
# Port 80 keeps working and redirects to HTTPS.

set -euo pipefail
trap 'echo "ERROR: ${BASH_SOURCE[0]##*/} stopped at line $LINENO: $BASH_COMMAND" >&2' ERR

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
CERT_DIR=/etc/itam/tls
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
# Prints the value of a .env key, or nothing when the key is absent (never fails).
envval() { { grep -E "^$1=" "$ENV_FILE" || true; } | tail -1 | cut -d= -f2-; }
setenv() {
  if grep -qE "^$1=" "$ENV_FILE"; then sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"; else echo "$1=$2" >> "$ENV_FILE"; fi
}

[[ $EUID -eq 0 ]] || die "run with sudo"
[[ -f "$ENV_FILE" ]] || die "install first: sudo bash scripts/install.sh"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
if [[ "${1:-}" == "--self-signed" ]]; then
  NAME="${2:-}"
  IP="$(envval ITAM_ALLOWED_HOSTS | cut -d, -f1)"
  SAN="IP:$IP"; [[ -n "$NAME" ]] && SAN="DNS:$NAME,$SAN"
  openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 \
    -keyout "$TMP/privkey.pem" -out "$TMP/fullchain.pem" \
    -subj "/CN=${NAME:-$IP}" -addext "subjectAltName=$SAN" 2>/dev/null
  CHAIN="$TMP/fullchain.pem"; KEY="$TMP/privkey.pem"
else
  CHAIN="${1:?Usage: $0 <fullchain.pem> <privkey.pem> [hostname]  |  $0 --self-signed [hostname]}"
  KEY="${2:?private key file required}"
  NAME="${3:-}"
fi

[[ -r "$CHAIN" && -r "$KEY" ]] || die "cannot read the certificate or key file"
openssl x509 -in "$CHAIN" -noout 2>/dev/null || die "$CHAIN is not a PEM certificate"
openssl x509 -in "$CHAIN" -noout -checkend 0 >/dev/null || die "the certificate has expired"
[[ "$(openssl x509 -in "$CHAIN" -noout -pubkey | openssl sha256)" == "$(openssl pkey -in "$KEY" -pubout 2>/dev/null | openssl sha256)" ]] \
  || die "the private key does not belong to the certificate"

install -d -m 0750 "$CERT_DIR"
install -m 0644 "$CHAIN" "$CERT_DIR/fullchain.pem"
install -m 0600 "$KEY" "$CERT_DIR/privkey.pem"
command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled && chcon -R -t container_file_t "$CERT_DIR"

HOSTS="$(envval ITAM_ALLOWED_HOSTS)"
if [[ -n "$NAME" && ",$HOSTS," != *",$NAME,"* ]]; then
  HOSTS="$NAME,$HOSTS"     # first entry is used by the container health check
fi
FIRST="$(echo "$HOSTS" | cut -d, -f1)"
ORIGINS="$(echo "$HOSTS" | tr ',' '\n' | sed 's|^|https://|' | paste -sd, -)"
cp -p "$ENV_FILE" "$ENV_FILE.before-https"
setenv ITAM_PUBLIC_SCHEME https
setenv ITAM_TLS_CERT_DIR "$CERT_DIR"
setenv ITAM_ALLOWED_HOSTS "$HOSTS"
setenv CSRF_TRUSTED_ORIGINS "$ORIGINS"
setenv ITAM_PUBLIC_URL "https://${NAME:-$FIRST}"

if systemctl is-active --quiet firewalld; then
  firewall-cmd -q --permanent --add-service=https && firewall-cmd -q --reload
fi
bash "$REPO_ROOT/scripts/compose.sh" prod up -d --wait --wait-timeout 300
bash "$REPO_ROOT/scripts/compose.sh" prod restart nginx-proxy >/dev/null

curl -fsS -k --max-time 10 --resolve "$FIRST:443:127.0.0.1" "https://$FIRST/api/v1/health/ready/" >/dev/null \
  || die "HTTPS check failed; previous settings saved in $ENV_FILE.before-https"
echo "HTTPS is enabled: https://${NAME:-$FIRST}/  (http:// now redirects)"
openssl x509 -in "$CERT_DIR/fullchain.pem" -noout -subject -enddate
