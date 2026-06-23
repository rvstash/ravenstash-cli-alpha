#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_cmd nfpm

VERSION="${RVN_VERSION:-$(rvn_version)}"
ARCH="${RVN_ARCH:-$(rvn_arch)}"
if [[ "$ARCH" == "unsupported" ]]; then
  echo "error: unsupported architecture $(uname -m)" >&2
  exit 1
fi

if [[ ! -x dist/pyinstaller/rvn/rvn ]]; then
  packaging/scripts/build-pyinstaller.sh
fi

mkdir -p build/nfpm dist/packages
sed \
  -e "s/__VERSION__/${VERSION}/g" \
  -e "s/__ARCH__/${ARCH}/g" \
  packaging/nfpm.yaml.in > build/nfpm/rvn.yaml

nfpm package \
  --packager deb \
  --config build/nfpm/rvn.yaml \
  --target "dist/packages/rvn_${VERSION}_${ARCH}.deb"
