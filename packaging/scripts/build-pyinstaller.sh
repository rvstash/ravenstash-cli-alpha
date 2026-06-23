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
  packaging/pyinstaller/rvn.spec

dist/pyinstaller/rvn/rvn --version
dist/pyinstaller/rvn/rvn --help >/dev/null
