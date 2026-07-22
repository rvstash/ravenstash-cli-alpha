#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_cmd tar

VERSION="${RVS_VERSION:-$(rvs_version)}"
ARCH="${RVS_ARCH:-$(rvs_arch)}"
if [[ "$ARCH" == "unsupported" ]]; then
  echo "error: unsupported architecture $(uname -m)" >&2
  exit 1
fi

if [[ ! -x dist/pyinstaller/rvs/rvs ]]; then
  packaging/scripts/build-pyinstaller.sh
fi

STAGING="build/release/rvs-v${VERSION}-linux-${ARCH}"
rm -rf "$STAGING"
mkdir -p "$STAGING"
cp -a dist/pyinstaller/rvs/. "$STAGING/"
cp README.md "$STAGING/README.md"

mkdir -p dist/release
tar -C build/release -czf "dist/release/rvs-v${VERSION}-linux-${ARCH}.tar.gz" \
  "rvs-v${VERSION}-linux-${ARCH}"
