#!/usr/bin/env bash
# Installs Docker Engine + Compose v2 on an AlmaLinux 10 STAGING host from Docker's
# official RHEL repository (docs/12 section 1). Prints the plan and does nothing unless
# called with --yes. Never touches SELinux or firewalld and never removes packages.
#
# Usage: sudo scripts/staging/install_docker.sh [--yes]
#
# Docker documents RHEL 10 but does not test derivatives: this script is how the
# AlmaLinux 10.2 compatibility check is performed, and its record must be kept.

set -euo pipefail

REPO_URL="https://download.docker.com/linux/rhel/docker-ce.repo"
GPG_URL="https://download.docker.com/linux/rhel/gpg"
# Fingerprint published at https://docs.docker.com/engine/install/rhel/ ; re-check it
# there on the day you install and stop if it differs.
EXPECTED_FPR="060A61C51B558A7F742B77AAC52FEB6B621E9F35"
PACKAGES=(docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin)
RECORD="/root/itam-docker-install-$(date +%Y%m%d-%H%M%S).txt"

cat <<PLAN
Plan:
  1. Refuse if Podman/runc/old Docker packages are installed (decide with the host owner).
  2. Install dnf-plugins-core and add $REPO_URL.
  3. Download Docker's GPG key, check fingerprint $EXPECTED_FPR, import it.
  4. dnf install ${PACKAGES[*]}
  5. systemctl enable --now docker
  6. Record versions in $RECORD
SELinux and firewalld are left as they are. No user is added to the docker group.
PLAN

if [[ "${1:-}" != "--yes" ]]; then
  echo
  echo "Dry run only. Re-run with --yes to install."
  exit 0
fi
[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }

CONFLICTS=()
for pkg in podman podman-docker buildah runc docker docker-client docker-common docker-engine; do
  rpm -q "$pkg" >/dev/null 2>&1 && CONFLICTS+=("$pkg")
done
if (( ${#CONFLICTS[@]} )); then
  echo "Conflicting packages installed: ${CONFLICTS[*]}" >&2
  echo "Docker's guide removes them first. Confirm nothing else on this host uses them, remove them yourself, then re-run." >&2
  exit 1
fi

dnf -y install dnf-plugins-core
if ! dnf config-manager --add-repo "$REPO_URL" 2>/dev/null; then
  dnf config-manager addrepo --from-repofile="$REPO_URL"   # dnf5 syntax
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$GPG_URL" -o "$TMP/docker.gpg"
FPR="$(gpg --show-keys --with-colons "$TMP/docker.gpg" | awk -F: '/^fpr:/ {print $10; exit}')"
if [[ "$FPR" != "$EXPECTED_FPR" ]]; then
  echo "GPG fingerprint mismatch: got '$FPR', expected '$EXPECTED_FPR'. Stopping." >&2
  exit 1
fi
rpm --import "$TMP/docker.gpg"
echo "GPG key verified and imported: $FPR"

if ! dnf -q makecache --repo docker-ce-stable; then
  echo "The docker-ce-stable repository does not resolve on this release (\$releasever=$(rpm -E %rhel))." >&2
  echo "Record this as a compatibility failure; do not point the repo at another distribution." >&2
  exit 1
fi
dnf -y install "${PACKAGES[@]}"
systemctl enable --now docker

{
  echo "ITAM staging Docker install record - $(date -Is)"
  grep PRETTY_NAME /etc/os-release
  echo "kernel $(uname -r) arch $(uname -m) selinux $(getenforce)"
  echo "gpg $FPR"
  rpm -q "${PACKAGES[@]}"
  docker version --format 'engine {{.Server.Version}} api {{.Server.APIVersion}}'
  docker compose version
  docker info --format 'storage {{.Driver}} cgroup {{.CgroupDriver}} v{{.CgroupVersion}} security {{json .SecurityOptions}}'
} | tee "$RECORD"
chmod 600 "$RECORD"

cat <<NEXT

Docker is installed. Run 'sudo docker run --rm hello-world' to confirm, then continue
with docs/12 section 9. The docker group is root-equivalent: add only approved admins.
NEXT
