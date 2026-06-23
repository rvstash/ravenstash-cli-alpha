#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_cmd sha256sum

VERSION="${RVN_VERSION:-$(rvn_version)}"
ARCH="${RVN_ARCH:-$(rvn_arch)}"

packaging/scripts/build-pyinstaller.sh
RVN_VERSION="$VERSION" RVN_ARCH="$ARCH" packaging/scripts/build-deb.sh
RVN_VERSION="$VERSION" RVN_ARCH="$ARCH" packaging/scripts/build-tarball.sh

mkdir -p dist/release
cp "dist/packages/rvn_${VERSION}_${ARCH}.deb" dist/release/

(
  cd dist/release
  rm -f "rvn-v${VERSION}-checksums.txt"
  sha256sum * > "rvn-v${VERSION}-checksums.txt"
)
