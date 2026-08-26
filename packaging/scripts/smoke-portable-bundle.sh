#!/usr/bin/env bash
set -euo pipefail

temporary_directory="$(mktemp -d)"
trap 'rm -rf -- "$temporary_directory"' EXIT
if [[ "${1:-}" == "--bundle" ]]; then
  bundle_directory="${2:?bundle directory is required}"
else
  release_directory="${1:-/release}"
  archive="${2:-}"
  if [[ -z "$archive" ]]; then
    shopt -s nullglob
    archives=("$release_directory"/rvs-v*-linux-amd64.tar.gz)
    shopt -u nullglob
    [[ "${#archives[@]}" -eq 1 ]] || {
      echo "error: expected exactly one rvs portable amd64 archive in ${release_directory}" >&2
      exit 1
    }
    archive="${archives[0]}"
  fi
  tar -xzf "$archive" -C "$temporary_directory"
  archive_root="$(basename "$archive" .tar.gz)"
  bundle_directory="${temporary_directory}/${archive_root}"
fi
[[ -x "${bundle_directory}/rvs" ]]

export HOME="${temporary_directory}/home"
install -d -m 0700 "$HOME"
"${bundle_directory}/rvs" --version
"${bundle_directory}/rvs" --help >/dev/null
"${bundle_directory}/ravenstash" --version
test -x "${bundle_directory}/docker-credential-rvs"

RVS_TOKEN="ci-smoke-token" "${bundle_directory}/rvs" auth status >/dev/null

set +e
doctor_output="$("${bundle_directory}/rvs" auth keyring doctor 2>&1)"
doctor_status=$?
set -e
[[ "$doctor_status" -eq 1 ]]
grep -F "Credential stores" <<<"$doctor_output" >/dev/null
grep -F "RVS_TOKEN set" <<<"$doctor_output" >/dev/null
