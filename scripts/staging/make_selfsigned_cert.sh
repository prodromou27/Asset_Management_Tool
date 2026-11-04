#!/usr/bin/env bash
# TEMPORARY self-signed certificate for a STAGING host reached by IP (docs/12 section 9).
# Browsers will warn; that is expected. Replace it with a certificate from the internal
# CA once the FQDN exists (same two file names, then restart nginx-proxy).
#
# Usage: sudo scripts/staging/make_selfsigned_cert.sh <ip> [short-name] [cert-dir]
#   cert-dir defaults to /etc/itam/tls. Existing files are never overwritten.

set -euo pipefail

IP="${1:?Usage: $0 <ip> [short-name] [cert-dir]}"
NAME="${2:-}"
DIR="${3:-/etc/itam/tls}"
DAYS=90

[[ $EUID -eq 0 ]] || { echo "Run with sudo (the key must be root-owned)." >&2; exit 1; }
[[ "$IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || { echo "Not an IPv4 address: $IP" >&2; exit 1; }
if [[ -e "$DIR/privkey.pem" || -e "$DIR/fullchain.pem" ]]; then
  echo "$DIR already holds a certificate; remove it yourself if you mean to replace it." >&2
  exit 1
fi

SAN="IP:$IP"
[[ -n "$NAME" ]] && SAN="$SAN,DNS:$NAME"

install -d -m 0750 -o root -g root "$DIR"
umask 077
openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days "$DAYS" \
  -keyout "$DIR/privkey.pem" -out "$DIR/fullchain.pem" \
  -subj "/O=ITAM STAGING ONLY/CN=$IP" \
  -addext "subjectAltName=$SAN" \
  -addext "basicConstraints=critical,CA:FALSE" \
  -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth" 2>/dev/null
chmod 0600 "$DIR/privkey.pem"
chmod 0644 "$DIR/fullchain.pem"

# Let the nginx-proxy container read the bind mount without disabling SELinux.
if command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled; then
  chcon -R -t container_file_t "$DIR"
fi

echo "Temporary certificate written to $DIR (valid $DAYS days, SAN $SAN)."
openssl x509 -in "$DIR/fullchain.pem" -noout -subject -enddate -fingerprint -sha256
echo "Compare this fingerprint with the browser warning page before accepting it."
