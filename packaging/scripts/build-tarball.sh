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
# `rvs update` refuses archives with link members, so every command alias ships
# as a regular copy of the launcher, like the other portable archives.
for alias in ravenstash docker-credential-rvs; do
  rm -f -- "$STAGING/$alias"
  install -m 0755 "$STAGING/rvs" "$STAGING/$alias"
done
cp README.md "$STAGING/README.md"
cp LICENSE "$STAGING/LICENSE"
cp NOTICE "$STAGING/NOTICE"

ARCHIVE="dist/release/rvs-v${VERSION}-linux-${ARCH}.tar.gz"
mkdir -p dist/release
tar \
  --sort=name \
  --mtime="@${SOURCE_DATE_EPOCH:-0}" \
  --owner=0 \
  --group=0 \
  --numeric-owner \
  -C build/release \
  -czf "$ARCHIVE" \
  "rvs-v${VERSION}-linux-${ARCH}"

members="$(tar -tvzf "$ARCHIVE")"
if grep -q '^[^d-]' <<<"$members"; then
  echo "error: ${ARCHIVE} contains members that are not regular files or directories:" >&2
  grep '^[^d-]' <<<"$members" >&2
  rm -f -- "$ARCHIVE"
  exit 1
fi
