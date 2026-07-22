#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_cmd sha256sum

VERSION="${RVS_VERSION:-$(rvs_version)}"
ARCH="${RVS_ARCH:-$(rvs_arch)}"

packaging/scripts/build-pyinstaller.sh
RVS_VERSION="$VERSION" RVS_ARCH="$ARCH" packaging/scripts/build-deb.sh
RVS_VERSION="$VERSION" RVS_ARCH="$ARCH" packaging/scripts/build-tarball.sh

mkdir -p dist/release
cp "dist/packages/rvs_${VERSION}_${ARCH}.deb" dist/release/

(
  cd dist/release
  rm -f "rvs-v${VERSION}-checksums.txt"
  sha256sum * > "rvs-v${VERSION}-checksums.txt"
)
