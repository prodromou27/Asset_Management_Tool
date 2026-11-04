#!/usr/bin/env bash
# One-command install and update for a single AlmaLinux host (docs/12 section 9).
#
#   sudo bash scripts/install.sh            first install, or update after "git pull"
#   sudo bash scripts/install.sh --ip X     use address X instead of the detected one
#
# First run: installs Docker if missing, writes .env (generated secrets, never printed),
# builds and starts the app on http://<server-ip>/ and offers to create the first
# administrator. Later runs rebuild and migrate. HTTPS is added afterwards with
# scripts/enable_https.sh. SELinux and firewalld stay enabled; only the web port opens.

set -euo pipefail
trap 'echo "ERROR: ${BASH_SOURCE[0]##*/} stopped at line $LINENO: $BASH_COMMAND" >&2' ERR

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
COMPOSE=(bash "$REPO_ROOT/scripts/compose.sh" prod)
DOCKER_GPG_FPR="060A61C51B558A7F742B77AAC52FEB6B621E9F35"   # docs.docker.com/engine/install/rhel

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
# Prints the value of a .env key, or nothing when the key is absent (never fails).
envval() { { grep -E "^$1=" "$ENV_FILE" || true; } | tail -1 | cut -d= -f2-; }

[[ $EUID -eq 0 ]] || die "run with sudo: sudo bash scripts/install.sh"
IP=""
[[ "${1:-}" == "--ip" ]] && IP="${2:?--ip needs an address}"

install_docker() {
  say "Installing Docker (official repository)"
  for pkg in podman podman-docker buildah runc; do
    rpm -q "$pkg" >/dev/null 2>&1 && die "'$pkg' is installed and conflicts with Docker. If nothing else on this server uses it: sudo dnf remove podman buildah runc podman-docker, then run this script again."
  done
  dnf -y -q install dnf-plugins-core curl gnupg2
  dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo 2>/dev/null \
    || dnf config-manager addrepo --from-repofile=https://download.docker.com/linux/rhel/docker-ce.repo
  local tmp; tmp="$(mktemp)"
  curl -fsSL https://download.docker.com/linux/rhel/gpg -o "$tmp"
  local fpr; fpr="$(gpg --show-keys --with-colons "$tmp" | awk -F: '/^fpr:/ {print $10; exit}')"
  [[ "$fpr" == "$DOCKER_GPG_FPR" ]] || die "Docker signing key fingerprint mismatch ($fpr)"
  rpm --import "$tmp"; rm -f "$tmp"
  dnf -y -q install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
  docker version --format 'Docker {{.Server.Version}} installed'
}

write_env() {
  [[ -n "$IP" ]] || IP="$(hostname -I | awk '{print $1}')"
  [[ "$IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || die "could not detect the server IP; run: sudo bash scripts/install.sh --ip <address>"
  local hosts="$IP" origins="http://$IP" name
  for name in "$(hostname -s)" "$(hostname -f 2>/dev/null || true)"; do
    if [[ -n "$name" && "$name" != localhost* && ",$hosts," != *",$name,"* ]]; then
      hosts="$hosts,$name"; origins="$origins,http://$name"
    fi
  done
  say "Writing .env for http://$IP (secrets generated, not displayed)"
  umask 077
  cat > "$ENV_FILE" <<ENV
# Generated $(date -Is) by scripts/install.sh. Never commit or share this file.
ITAM_ENV=staging
ITAM_PUBLIC_SCHEME=http
ITAM_PUBLIC_URL=http://$IP
# The first entry is used by the container health check.
ITAM_ALLOWED_HOSTS=$hosts
CSRF_TRUSTED_ORIGINS=$origins
ITAM_TIMEZONE=Asia/Nicosia
ITAM_LOG_LEVEL=INFO
POSTGRES_DB=itam
POSTGRES_USER=itam
POSTGRES_PASSWORD=$(openssl rand -hex 32)
DJANGO_SECRET_KEY=$(openssl rand -base64 96 | tr -d '\n=+/' | cut -c1-80)
ITAM_IMPORT_ENCRYPTION_KEY=$(openssl rand 32 | base64 | tr '+/' '-_')
ITAM_IMPORT_RETENTION_DAYS=90
ITAM_EXPORT_RETENTION_HOURS=24
ITAM_EXPORT_MAX_ROWS=100000
ITAM_ALLOW_LIVE_INTEGRATIONS=false
ENV
  chmod 600 "$ENV_FILE"
  echo "Keep a safe copy of $ENV_FILE: without it the database password and keys are lost."
}

command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 || install_docker
systemctl is-active --quiet docker || systemctl start docker

FIRST_INSTALL=no
if [[ ! -f "$ENV_FILE" ]]; then
  write_env
  FIRST_INSTALL=yes
fi
SCHEME="$(envval ITAM_PUBLIC_SCHEME)"; SCHEME="${SCHEME:-https}"
HOST="$(envval ITAM_ALLOWED_HOSTS | cut -d, -f1)"

# Let containers read the proxy config (and certificate) without disabling SELinux.
if command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled; then
  chcon -R -t container_file_t "$REPO_ROOT/infra/nginx"
  CERT_DIR="$(envval ITAM_TLS_CERT_DIR)"
  [[ -n "$CERT_DIR" && -d "$CERT_DIR" ]] && chcon -R -t container_file_t "$CERT_DIR"
fi

say "Building the application (first time takes several minutes)"
"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" build --pull

say "Starting the database and updating its structure"
"${COMPOSE[@]}" up -d --wait postgres redis
"${COMPOSE[@]}" run --rm --no-deps api python manage.py migrate --no-input

say "Starting the application"
"${COMPOSE[@]}" up -d --wait --wait-timeout 300 --remove-orphans

if systemctl is-active --quiet firewalld; then
  firewall-cmd -q --permanent --add-service=http
  [[ "$SCHEME" == "https" ]] && firewall-cmd -q --permanent --add-service=https
  firewall-cmd -q --reload
fi

say "Checking"
if [[ "$SCHEME" == "https" ]]; then
  CHECK=(curl -fsS -k --max-time 10 --resolve "$HOST:443:127.0.0.1" "https://$HOST/api/v1/health/ready/")
else
  CHECK=(curl -fsS --max-time 10 -H "Host: $HOST" "http://127.0.0.1/api/v1/health/ready/")
fi
"${CHECK[@]}" >/dev/null || die "the application did not answer; see: sudo bash scripts/compose.sh prod logs --tail=100"
echo "Application is healthy."

if [[ "$FIRST_INSTALL" == "yes" && -t 0 ]]; then
  read -r -p $'\nCreate the first administrator now? [Y/n] ' ANSWER
  if [[ ! "$ANSWER" =~ ^[Nn] ]]; then
    read -r -p "Username: " U
    read -r -p "Full name: " N
    read -r -p "Email (optional): " E
    "${COMPOSE[@]}" exec api python manage.py bootstrap_admin --username "$U" --display-name "$N" --email "$E"
  fi
fi

cat <<DONE

Done. Open $SCHEME://$HOST/ in a browser.
  Add an administrator later: sudo bash scripts/bootstrap_admin.sh prod <username> "<Full Name>" [email]
  Enable HTTPS:               sudo bash scripts/enable_https.sh <fullchain.pem> <privkey.pem> [hostname]
  Update:                     git pull && sudo bash scripts/install.sh
DONE
