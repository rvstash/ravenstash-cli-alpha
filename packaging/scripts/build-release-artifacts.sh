#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_cmd sha256sum
require_cmd cyclonedx-py
require_cmd uv

VERSION="${RVS_VERSION:-$(rvs_version)}"
ARCH="${RVS_ARCH:-$(rvs_arch)}"
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git log -1 --format=%ct 2>/dev/null || echo 0)}"

packaging/scripts/build-pyinstaller.sh
RVS_VERSION="$VERSION" RVS_ARCH="$ARCH" packaging/scripts/build-deb.sh
RVS_VERSION="$VERSION" RVS_ARCH="$ARCH" packaging/scripts/build-tarball.sh

mkdir -p dist/release
cp "dist/packages/rvs_${VERSION}_${ARCH}.deb" dist/release/
install -m 0755 packaging/install.sh dist/release/install.sh
uv export \
  --frozen \
  --no-dev \
  --no-group release \
  --format requirements-txt \
  --output-file build/release/runtime-requirements.txt
cyclonedx-py requirements \
  build/release/runtime-requirements.txt \
  --pyproject pyproject.toml \
  --spec-version 1.6 \
  --output-reproducible \
  --output-format JSON \
  --output-file "dist/release/rvs-v${VERSION}-sbom.cdx.json"

(
  cd dist/release
  rm -f "rvs-v${VERSION}-checksums.txt"
  find . -maxdepth 1 -type f ! -name '*-checksums.txt' -printf '%f\n' \
    | LC_ALL=C sort \
    | xargs sha256sum > "rvs-v${VERSION}-checksums.txt"
)
