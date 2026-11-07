#!/usr/bin/env bash
set -euo pipefail
destination="${1:?Pass a task-owned tools directory}"
version=0.76.2
sha256=bc0fc726e017b8927a62b2d3531d7a84ee01769daf5c99ed866dced54089fdbf
mkdir -p "$destination"
archive="$destination/trivy-$version.tar.gz"
curl --fail --location --retry 3 --output "$archive" \
  "https://github.com/aquasecurity/trivy/releases/download/v$version/trivy_${version}_Linux-64bit.tar.gz"
printf '%s  %s\n' "$sha256" "$archive" | sha256sum --check --status
tar -xzf "$archive" -C "$destination" trivy
rm -f -- "$archive"
"$destination/trivy" --version
