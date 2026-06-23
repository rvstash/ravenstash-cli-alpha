#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

require_cmd() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "error: required command '$name' was not found on PATH" >&2
    exit 127
  fi
}

rvn_version() {
  python3 - <<'PY'
from pathlib import Path
import tomllib

with Path("pyproject.toml").open("rb") as f:
    print(tomllib.load(f)["project"]["version"])
PY
}

rvn_arch() {
  case "$(uname -m)" in
    x86_64|amd64) echo "amd64" ;;
    aarch64|arm64) echo "arm64" ;;
    *) echo "unsupported" ;;
  esac
}
