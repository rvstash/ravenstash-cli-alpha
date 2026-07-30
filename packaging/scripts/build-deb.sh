#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_cmd dpkg-deb

VERSION="${RVS_VERSION:-$(rvs_version)}"
ARCH="${RVS_ARCH:-$(rvs_arch)}"
if [[ "$ARCH" == "unsupported" ]]; then
  echo "error: unsupported architecture $(uname -m)" >&2
  exit 1
fi

if [[ ! -x dist/pyinstaller/rvs/rvs ]]; then
  packaging/scripts/build-pyinstaller.sh
fi

STAGING="build/deb/rvs_${VERSION}_${ARCH}"
rm -rf "$STAGING"
mkdir -p \
  "$STAGING/DEBIAN" \
  "$STAGING/usr/lib/rvs" \
  "$STAGING/usr/bin" \
  "$STAGING/usr/share/doc/rvs"
cp -a dist/pyinstaller/rvs/. "$STAGING/usr/lib/rvs/"
ln -s ../lib/rvs/rvs "$STAGING/usr/bin/rvs"
ln -s ../lib/rvs/rvs "$STAGING/usr/bin/ravenstash"
cp README.md "$STAGING/usr/share/doc/rvs/README.md"
install -m 0755 packaging/scripts/postinstall.sh "$STAGING/DEBIAN/postinst"
cat > "$STAGING/DEBIAN/control" <<EOF
Package: rvs
Version: ${VERSION}
Architecture: ${ARCH}
Maintainer: Ravenstash <support@ravenstash.com>
Depends: ca-certificates, gpgv
Section: devel
Priority: optional
Homepage: https://ravenstash.com
Description: Ravenstash developer CLI
 A self-contained Python 3.14 command-line client for Ravenstash.
EOF

find "$STAGING" -exec touch -h -d "@${SOURCE_DATE_EPOCH:-0}" {} +
mkdir -p dist/packages
dpkg-deb --root-owner-group --build "$STAGING" "dist/packages/rvs_${VERSION}_${ARCH}.deb"
