#!/usr/bin/env bash
# Read-only preflight for a STAGING host (docs/12 section 0 and section 9).
# Changes nothing: it only reports. Run it as a normal user; a few checks need sudo
# to read details and say so when they are skipped.
#
# Usage: scripts/staging/preflight.sh

set -uo pipefail

FAILS=0
WARNS=0
ok()   { printf '  [ OK ] %s\n' "$*"; }
warn() { printf '  [WARN] %s\n' "$*"; WARNS=$((WARNS + 1)); }
fail() { printf '  [FAIL] %s\n' "$*"; FAILS=$((FAILS + 1)); }
have() { command -v "$1" >/dev/null 2>&1; }

echo "== Operating system"
if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  if [[ "${ID:-}" == "almalinux" && "${VERSION_ID:-}" == 10.* ]]; then
    ok "${PRETTY_NAME:-$ID $VERSION_ID}"
    [[ "${VERSION_ID}" == "10.2" ]] || warn "Expected AlmaLinux 10.2 (docs/12); found ${VERSION_ID}. Record and approve."
  else
    fail "Not AlmaLinux 10.x: ${PRETTY_NAME:-unknown}"
  fi
else
  fail "/etc/os-release not readable"
fi
ARCH="$(uname -m)"
[[ "$ARCH" == "x86_64" || "$ARCH" == "aarch64" ]] && ok "Architecture $ARCH" || fail "Unsupported architecture $ARCH"
ok "Kernel $(uname -r)"

echo "== Security"
if have getenforce; then
  MODE="$(getenforce)"
  [[ "$MODE" == "Enforcing" ]] && ok "SELinux Enforcing" || fail "SELinux is $MODE; it must stay Enforcing (do not disable it)"
else
  fail "getenforce not found"
fi
if have firewall-cmd; then
  STATE="$(firewall-cmd --state 2>/dev/null || true)"
  [[ "$STATE" == "running" ]] && ok "firewalld running" || fail "firewalld is not running ($STATE)"
else
  fail "firewalld not installed"
fi
if have timedatectl; then
  SYNC="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)"
  [[ "$SYNC" == "yes" ]] && ok "Clock synchronised (NTP)" || warn "Clock not NTP-synchronised; timestamps and certificates depend on it"
fi
if have dnf; then
  UPDATES="$(dnf -q check-update 2>/dev/null | grep -c '^[[:alnum:]]' || true)"
  [[ "$UPDATES" == "0" ]] && ok "No pending package updates" || warn "$UPDATES package update(s) pending; patch the host first"
fi

echo "== Resources (docs/12 sizing: 8 vCPU, 24-32 GB for production; staging can be smaller)"
CPUS="$(nproc)"
MEM_GB="$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo)"
(( CPUS >= 4 )) && ok "$CPUS vCPU" || warn "$CPUS vCPU; at least 4 recommended for staging"
(( MEM_GB >= 8 )) && ok "${MEM_GB} GB RAM" || warn "${MEM_GB} GB RAM; at least 8 GB recommended (limits total 11 GB)"
DOCKER_ROOT=/var/lib/docker
[[ -d "$DOCKER_ROOT" ]] || DOCKER_ROOT=/var/lib
FREE_GB="$(df -P -BG "$DOCKER_ROOT" | awk 'NR==2 {gsub("G","",$4); print $4}')"
(( FREE_GB >= 30 )) && ok "${FREE_GB} GB free under $DOCKER_ROOT" || warn "${FREE_GB} GB free under $DOCKER_ROOT; 30 GB+ recommended (images, database)"

echo "== Container runtime"
CONFLICTS=""
if have rpm; then
  for pkg in podman podman-docker buildah runc docker docker-client docker-common docker-engine; do
    rpm -q "$pkg" >/dev/null 2>&1 && CONFLICTS="$CONFLICTS $pkg"
  done
fi
[[ -z "$CONFLICTS" ]] && ok "No conflicting packages" || warn "Installed packages that conflict with Docker CE:$CONFLICTS (decide with the host owner; do not remove blindly)"
if have docker; then
  ok "docker: $(docker --version 2>/dev/null)"
  if docker compose version >/dev/null 2>&1; then ok "$(docker compose version)"; else fail "docker compose plugin missing"; fi
  if systemctl is-active --quiet docker; then ok "docker.service active"; else warn "docker.service not active"; fi
  if docker info >/dev/null 2>&1; then
    docker info --format '{{json .SecurityOptions}}' | grep -q selinux \
      && ok "Docker SELinux support enabled" \
      || warn "Docker runs without --selinux-enabled; containers are not SELinux-confined (record this)"
  else
    warn "Cannot query 'docker info' as $(id -un); re-run with sudo for runtime details"
  fi
else
  warn "Docker not installed yet (scripts/staging/install_docker.sh)"
fi

echo "== Network"
if have ss; then
  if ss -ltnH '( sport = :443 )' 2>/dev/null | grep -q .; then
    fail "TCP 443 already in use: $(ss -ltnpH '( sport = :443 )' 2>/dev/null | head -1)"
  else
    ok "TCP 443 is free"
  fi
fi
IPS="$(hostname -I 2>/dev/null | xargs)"
ok "Host addresses: ${IPS:-unknown}; short name: $(hostname -s)"
if have curl; then
  curl -fsS -o /dev/null --max-time 10 https://download.docker.com/ && ok "Reaches download.docker.com" || warn "Cannot reach download.docker.com (needed to install Docker)"
  curl -fsS -o /dev/null --max-time 10 https://registry-1.docker.io/v2/ 2>/dev/null; RC=$?
  # The registry answers 401 to anonymous probes; curl -f turns that into exit 22.
  [[ $RC -eq 0 || $RC -eq 22 ]] && ok "Reaches Docker Hub registry" || warn "Cannot reach Docker Hub (base images are pulled from it)"
else
  warn "curl not installed"
fi
have openssl && ok "openssl present" || fail "openssl missing (needed for the temporary certificate and secrets)"
have python3 && ok "python3 present" || fail "python3 missing (deploy.sh inspects the Compose config with it)"
have git && ok "git present" || warn "git missing (or copy the release archive instead)"

echo
echo "Result: $FAILS failure(s), $WARNS warning(s). Nothing was changed."
(( FAILS == 0 ))
