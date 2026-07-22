#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

PYINSTALLER_BIN="${PYINSTALLER:-pyinstaller}"
if ! command -v "$PYINSTALLER_BIN" >/dev/null 2>&1; then
  if [[ -x .venv/bin/pyinstaller ]]; then
    PYINSTALLER_BIN=".venv/bin/pyinstaller"
  else
    echo "error: required command 'pyinstaller' was not found on PATH or at .venv/bin/pyinstaller" >&2
    exit 127
  fi
fi

mkdir -p build/pyinstaller dist/pyinstaller
"$PYINSTALLER_BIN" \
  --clean \
  --noconfirm \
  --distpath dist/pyinstaller \
  --workpath build/pyinstaller \
  packaging/pyinstaller/rvs.spec

ln -sfn rvs dist/pyinstaller/rvs/ravenstash
dist/pyinstaller/rvs/rvs --version
dist/pyinstaller/rvs/rvs --help >/dev/null
dist/pyinstaller/rvs/ravenstash --version
