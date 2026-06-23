#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_cmd tar

VERSION="${RVN_VERSION:-$(rvn_version)}"
ARCH="${RVN_ARCH:-$(rvn_arch)}"
if [[ "$ARCH" == "unsupported" ]]; then
  echo "error: unsupported architecture $(uname -m)" >&2
  exit 1
fi

if [[ ! -x dist/pyinstaller/rvn/rvn ]]; then
  packaging/scripts/build-pyinstaller.sh
fi

STAGING="build/release/rvn-v${VERSION}-linux-${ARCH}"
rm -rf "$STAGING"
mkdir -p "$STAGING"
cp -a dist/pyinstaller/rvn/. "$STAGING/"
cp README.md "$STAGING/README.md"

mkdir -p dist/release
tar -C build/release -czf "dist/release/rvn-v${VERSION}-linux-${ARCH}.tar.gz" \
  "rvn-v${VERSION}-linux-${ARCH}"
