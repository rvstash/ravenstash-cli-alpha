#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_cmd apt-ftparchive
require_cmd gzip

VERSION="${RVS_VERSION:-$(rvs_version)}"
ARCH="${RVS_ARCH:-$(rvs_arch)}"
APT_REPO_DIR="${APT_REPO_DIR:-dist/apt}"
CODENAME="${RVS_APT_CODENAME:-stable}"
COMPONENT="${RVS_APT_COMPONENT:-main}"
DEB="dist/packages/rvs_${VERSION}_${ARCH}.deb"

if [[ ! -f "$DEB" ]]; then
  echo "error: package not found: $DEB" >&2
  echo "run packaging/scripts/build-deb.sh first" >&2
  exit 1
fi

mkdir -p "$APT_REPO_DIR"
APT_REPO_DIR="$(cd "$APT_REPO_DIR" && pwd)"

POOL_DIR="${APT_REPO_DIR}/pool/${COMPONENT}/r/rvs"
BINARY_DIR="${APT_REPO_DIR}/dists/${CODENAME}/${COMPONENT}/binary-${ARCH}"
mkdir -p "$POOL_DIR" "$BINARY_DIR"
cp "$DEB" "$POOL_DIR/"

(cd "$APT_REPO_DIR" && apt-ftparchive packages pool) > "${BINARY_DIR}/Packages"
gzip -kf "${BINARY_DIR}/Packages"

cat > "${APT_REPO_DIR}/apt-ftparchive-release.conf" <<EOF
APT::FTPArchive::Release {
  Origin "Ravenstash";
  Label "Ravenstash";
  Suite "${CODENAME}";
  Codename "${CODENAME}";
  Architectures "${ARCH}";
  Components "${COMPONENT}";
  Description "Ravenstash rvs CLI packages";
};
EOF

apt-ftparchive \
  -c "${APT_REPO_DIR}/apt-ftparchive-release.conf" \
  release "${APT_REPO_DIR}/dists/${CODENAME}" \
  > "${APT_REPO_DIR}/dists/${CODENAME}/Release"

if [[ -n "${RVS_APT_GPG_KEY_ID:-}" ]]; then
  require_cmd gpg
  gpg --batch --yes --local-user "$RVS_APT_GPG_KEY_ID" \
    --output "${APT_REPO_DIR}/dists/${CODENAME}/InRelease" \
    --clearsign "${APT_REPO_DIR}/dists/${CODENAME}/Release"
  gpg --batch --yes --local-user "$RVS_APT_GPG_KEY_ID" \
    --output "${APT_REPO_DIR}/dists/${CODENAME}/Release.gpg" \
    --detach-sign "${APT_REPO_DIR}/dists/${CODENAME}/Release"
else
  echo "warning: RVS_APT_GPG_KEY_ID not set; APT repo metadata is unsigned" >&2
fi
