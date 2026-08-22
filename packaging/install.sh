#!/usr/bin/env bash
set -euo pipefail

export PATH="/usr/sbin:/usr/bin:/sbin:/bin"

readonly repository_url="https://releases.ravenstash.com/rvs/apt"
readonly compatibility_channel="v0.4"
readonly signing_key_url="${repository_url}/ravenstash-rvs.gpg"
readonly signing_key_fingerprint="3B7C20FC370D1A7C813DF3A2E9679F951AD8BAA0"
readonly keyring_path="/etc/apt/keyrings/ravenstash-rvs.gpg"
readonly source_path="/etc/apt/sources.list.d/ravenstash-rvs.list"
readonly expected_source="deb [arch=amd64 signed-by=${keyring_path}] ${repository_url} ${compatibility_channel} main"
readonly legacy_source="deb [arch=amd64 signed-by=${keyring_path}] ${repository_url} stable main"
readonly repair="${RVS_INSTALL_REPAIR:-0}"

say() {
  printf 'rvs installer: %s\n' "$*"
}

fail() {
  printf 'rvs installer: error: %s\n' "$*" >&2
  exit 1
}

for command in apt-get awk curl dpkg gpg install mktemp; do
  command -v "$command" >/dev/null 2>&1 || {
    if [[ "$command" == "gpg" ]]; then
      continue
    fi
    fail "required command not found: ${command}"
  }
done

if [[ ! -r /etc/os-release ]]; then
  fail "cannot identify this operating system"
fi
# shellcheck disable=SC1091
source /etc/os-release
case "${ID:-}" in
  ubuntu)
    major="${VERSION_ID%%.*}"
    if [[ ! "$major" =~ ^[0-9]+$ ]] || (( major < 20 )); then
      fail "Ubuntu 20.04 or newer is required"
    fi
    ;;
  debian)
    major="${VERSION_ID%%.*}"
    if [[ ! "$major" =~ ^[0-9]+$ ]] || (( major < 11 )); then
      fail "Debian 11 or newer is required"
    fi
    ;;
  *)
    fail "only Ubuntu 20.04+ and Debian 11+ are supported"
    ;;
esac

if [[ "$(dpkg --print-architecture)" != "amd64" ]]; then
  fail "the Ravenstash APT repository currently supports amd64 Linux only"
fi

if [[ "${EUID}" -eq 0 ]]; then
  as_root() {
    "$@"
  }
elif command -v sudo >/dev/null 2>&1; then
  as_root() {
    sudo "$@"
  }
else
  fail "run as root or install sudo"
fi

if ! command -v gpg >/dev/null 2>&1; then
  say "installing signing-key verification tools"
  as_root apt-get update -qq
  as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ca-certificates gnupg
fi

temporary_directory="$(mktemp -d)"
temporary_key="${temporary_directory}/ravenstash-rvs.gpg"
trap 'rm -rf "$temporary_directory"' EXIT

say "downloading and verifying the Ravenstash APT signing key"
curl --proto '=https' --proto-redir '=https' --tlsv1.2 \
  -fsSL "$signing_key_url" -o "$temporary_key"
actual_fingerprint="$(
  gpg --batch --with-colons --import-options show-only --import "$temporary_key" 2>/dev/null \
    | awk -F: '$1 == "fpr" { print $10; exit }'
)"

if [[ "$actual_fingerprint" != "$signing_key_fingerprint" ]]; then
  fail "the downloaded signing key has an unexpected fingerprint"
fi

if [[ -e "$keyring_path" ]]; then
  existing_fingerprint="$(
    gpg --batch --with-colons --import-options show-only --import "$keyring_path" 2>/dev/null \
      | awk -F: '$1 == "fpr" { print $10; exit }'
  )"
  if [[ "$existing_fingerprint" != "$signing_key_fingerprint" && "$repair" != "1" ]]; then
    fail "an unexpected Ravenstash keyring already exists; inspect it, then rerun with RVS_INSTALL_REPAIR=1 to replace it"
  fi
fi
if [[ -e "$source_path" ]]; then
  existing_source="$(<"$source_path")"
  if [[ "$existing_source" != "$expected_source" ]] \
    && [[ "$existing_source" != "$legacy_source" ]] \
    && [[ "$repair" != "1" ]]; then
    fail "a conflicting Ravenstash APT source exists; inspect it, then rerun with RVS_INSTALL_REPAIR=1 to replace it"
  fi
fi

as_root install -d -m 0755 /etc/apt/keyrings
as_root install -m 0644 "$temporary_key" "$keyring_path"
printf '%s\n' "$expected_source" | as_root tee "$source_path" >/dev/null

say "installing rvs"
as_root apt-get update -qq
as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq rvs

installed_version="$(dpkg-query -W -f='${Version}' rvs)"
say "installed rvs ${installed_version} on compatibility channel ${compatibility_channel}"
say "next: rvs auth login"
