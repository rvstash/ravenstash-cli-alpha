#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_cmd nfpm

VERSION="${RVS_VERSION:-$(rvs_version)}"
ARCH="${RVS_ARCH:-$(rvs_arch)}"
if [[ "$ARCH" == "unsupported" ]]; then
  echo "error: unsupported architecture $(uname -m)" >&2
  exit 1
fi

if [[ ! -x dist/pyinstaller/rvs/rvs ]]; then
  packaging/scripts/build-pyinstaller.sh
fi

mkdir -p build/nfpm dist/packages
sed \
  -e "s/__VERSION__/${VERSION}/g" \
  -e "s/__ARCH__/${ARCH}/g" \
  packaging/nfpm.yaml.in > build/nfpm/rvs.yaml

nfpm package \
  --packager deb \
  --config build/nfpm/rvs.yaml \
  --target "dist/packages/rvs_${VERSION}_${ARCH}.deb"
