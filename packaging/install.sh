#!/usr/bin/env bash
set -euo pipefail

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

readonly repository_url="https://releases.ravenstash.com/rvs/apt"
readonly github_release_url="https://github.com/rvstash/ravenstash-cli-alpha/releases/download"
readonly release_version="0.8.9"
readonly compatibility_channel="v0.8"
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

print_success_banner() {
  if [[ "${RVS_INSTALL_NO_BANNER:-0}" == "1" ]]; then
    return
  fi

  cat <<'RAVENSTASH_BANNER'

  █████████████████████████▄▄▄
  █████████████████████████████▄▄
  ████████████████████████████████▄
  █████████████████████████████████▄
  ██████████████████████████████████▄
  ███████▀▀▀▀▀      ▀▀███████████████▄
  ████████▀      ▄▄▄▄   ▀▀▀███████████
  ██████▀         ▀▀         ▀████████
  ████▀                  ▄▄▄▄▄▄███████
  ███▀               ▄███████████████▀
  ██▀               ████████████████▀
  ▀▀               ▄███████████████▀
                   ▀█████████████▀
                    ██████████▀▀
                     █████████
                      ▀████████▄
                       ▀████████▄
                        ▀████████▄
                          █████████
                           ▀▀███████
                                ▀▀▀██▄

              RAVENSTASH
       CLI installed successfully
RAVENSTASH_BANNER
}

fail() {
  printf 'rvs installer: error: %s\n' "$*" >&2
  exit 1
}

has_os_family() {
  local candidate="$1"
  [[ " ${ID:-} ${ID_LIKE:-} " == *" ${candidate} "* ]]
}

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    fail "this installation step needs root; run as root or install sudo"
  fi
}

verify_signing_key() {
  local key="$1"
  local actual_fingerprint
  actual_fingerprint="$(
    gpg --batch --with-colons --import-options show-only --import "$key" 2>/dev/null \
      | awk -F: '$1 == "fpr" { print $10; exit }'
  )"
  if [[ "$actual_fingerprint" != "$signing_key_fingerprint" ]]; then
    fail "the downloaded signing key has an unexpected fingerprint"
  fi
}

reconcile_legacy_portable_links() {
  [[ -n "${HOME:-}" && "$HOME" == /* && "$HOME" != "/" ]] || return
  local bin_directory="${HOME}/.local/bin"
  local install_root="${HOME}/.local/share/rvs"
  local command_name link_path link_target
  for command_name in rvs ravenstash docker-credential-rvs; do
    link_path="${bin_directory}/${command_name}"
    if [[ -L "$link_path" ]]; then
      link_target="$(readlink "$link_path")"
      case "$link_target" in
        "${install_root}/"*/"${command_name}")
          ln -sfn "/usr/bin/${command_name}" "$link_path"
          say "redirected legacy portable command ${link_path} to the APT installation"
          ;;
      esac
    elif [[ -e "$link_path" ]]; then
      say "notice: ${link_path} was not installed by Ravenstash and may shadow /usr/bin/${command_name}"
    fi
  done
}

install_apt_package() {
  local temporary_directory="$1"
  local temporary_key="${temporary_directory}/ravenstash-rvs.gpg"

  for command in apt-get awk curl dpkg install ln mktemp readlink tee; do
    command -v "$command" >/dev/null 2>&1 || fail "required command not found: ${command}"
  done
  if [[ "$(dpkg --print-architecture)" != "amd64" ]]; then
    fail "the Ravenstash APT repository currently supports amd64 Linux only"
  fi
  if ! command -v gpg >/dev/null 2>&1; then
    say "installing signing-key verification tools"
    as_root apt-get update -qq
    as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ca-certificates gnupg
  fi

  say "downloading and verifying the Ravenstash APT signing key"
  curl --proto '=https' --proto-redir '=https' --tlsv1.2 \
    -fsSL "$signing_key_url" -o "$temporary_key"
  verify_signing_key "$temporary_key"

  if [[ -e "$keyring_path" ]]; then
    local existing_fingerprint
    existing_fingerprint="$(
      gpg --batch --with-colons --import-options show-only --import "$keyring_path" 2>/dev/null \
        | awk -F: '$1 == "fpr" { print $10; exit }'
    )"
    if [[ "$existing_fingerprint" != "$signing_key_fingerprint" && "$repair" != "1" ]]; then
      fail "an unexpected Ravenstash keyring already exists; inspect it, then rerun with RVS_INSTALL_REPAIR=1 to replace it"
    fi
  fi
  if [[ -e "$source_path" ]]; then
    local existing_source
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

  say "installing rvs with APT"
  as_root apt-get update -qq
  as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq rvs

  local installed_version
  installed_version="$(dpkg-query -W -f='${Version}' rvs)"
  reconcile_legacy_portable_links
  say "installed rvs ${installed_version} on compatibility channel ${compatibility_channel}"
}

require_portable_tools() {
  if command -v gpg >/dev/null 2>&1 \
    && command -v sha256sum >/dev/null 2>&1 \
    && command -v tar >/dev/null 2>&1; then
    return
  fi
  say "installing portable archive verification tools"
  if command -v dnf >/dev/null 2>&1; then
    local rpm_packages=(ca-certificates gzip tar)
    command -v sha256sum >/dev/null 2>&1 || rpm_packages+=(coreutils)
    if ! command -v gpg >/dev/null 2>&1; then
      rpm_packages+=(gnupg2)
    fi
    as_root dnf install -y "${rpm_packages[@]}"
  elif command -v yum >/dev/null 2>&1; then
    local yum_packages=(ca-certificates gzip tar)
    command -v sha256sum >/dev/null 2>&1 || yum_packages+=(coreutils)
    if ! command -v gpg >/dev/null 2>&1; then
      yum_packages+=(gnupg2)
    fi
    as_root yum install -y "${yum_packages[@]}"
  elif command -v zypper >/dev/null 2>&1; then
    local suse_packages=(ca-certificates gzip tar)
    command -v sha256sum >/dev/null 2>&1 || suse_packages+=(coreutils)
    if ! command -v gpg >/dev/null 2>&1; then
      suse_packages+=(gpg2)
    fi
    as_root zypper --non-interactive install "${suse_packages[@]}"
  elif command -v pacman >/dev/null 2>&1; then
    as_root pacman --sync --needed --noconfirm ca-certificates coreutils gnupg gzip tar
  else
    fail "gpg, sha256sum, and tar are required; install GnuPG, coreutils, and tar, then rerun"
  fi
  command -v gpg >/dev/null 2>&1 || fail "GnuPG installation completed but gpg is unavailable"
}

portable_architecture() {
  case "$(uname -m)" in
    x86_64 | amd64) printf 'amd64\n' ;;
    aarch64 | arm64)
      fail "Linux arm64 artifacts are not published yet; use RVS_TOKEN with a supported runner or build from source"
      ;;
    *) fail "unsupported CPU architecture: $(uname -m)" ;;
  esac
}

require_glibc_228() {
  local libc_version ldd_output
  if ! libc_version="$(getconf GNU_LIBC_VERSION 2>/dev/null)"; then
    ldd_output="$(ldd --version 2>&1 || true)"
    if grep -qi musl <<<"$ldd_output"; then
      fail "Alpine/musl needs a separate rvs build, which is not published yet; this installer will not run a glibc binary on musl"
    fi
    fail "could not identify a supported glibc runtime"
  fi
  libc_version="${libc_version#glibc }"
  local major="${libc_version%%.*}"
  local remainder="${libc_version#*.}"
  local minor="${remainder%%.*}"
  if [[ ! "$major" =~ ^[0-9]+$ || ! "$minor" =~ ^[0-9]+$ ]] \
    || (( major < 2 || (major == 2 && minor < 28) )); then
    fail "the portable rvs build requires glibc 2.28 or newer (found ${libc_version})"
  fi
}

install_portable_archive() {
  local temporary_directory="$1"
  local architecture
  architecture="$(portable_architecture)"
  require_glibc_228
  require_portable_tools
  for command in awk curl gpg install mktemp sha256sum tar; do
    command -v "$command" >/dev/null 2>&1 || fail "required command not found: ${command}"
  done

  local archive_name="rvs-v${release_version}-linux-${architecture}.tar.gz"
  local checksums_name="rvs-v${release_version}-checksums.txt"
  local signature_name="${checksums_name}.asc"
  local release_url="${github_release_url}/v${release_version}"
  local temporary_key="${temporary_directory}/ravenstash-rvs.gpg"

  say "downloading the signed portable rvs ${release_version} archive"
  curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fsSL \
    "${release_url}/${archive_name}" -o "${temporary_directory}/${archive_name}"
  curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fsSL \
    "${release_url}/${checksums_name}" -o "${temporary_directory}/${checksums_name}"
  curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fsSL \
    "${release_url}/${signature_name}" -o "${temporary_directory}/${signature_name}"
  curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fsSL \
    "$signing_key_url" -o "$temporary_key"
  verify_signing_key "$temporary_key"
  local temporary_gnupg="${temporary_directory}/gnupg"
  install -d -m 0700 "$temporary_gnupg"
  gpg --homedir "$temporary_gnupg" --batch --import "$temporary_key" >/dev/null 2>&1 \
    || fail "the Ravenstash signing key could not be imported"
  gpg --homedir "$temporary_gnupg" --batch --verify \
    "${temporary_directory}/${signature_name}" \
    "${temporary_directory}/${checksums_name}" >/dev/null 2>&1 \
    || fail "the portable release checksum signature is invalid"

  local expected_checksum
  expected_checksum="$(
    awk -v filename="$archive_name" '$2 == filename { print; found = 1 } END { if (!found) exit 1 }' \
      "${temporary_directory}/${checksums_name}"
  )" || fail "the signed checksum inventory does not contain ${archive_name}"
  printf '%s\n' "$expected_checksum" \
    | (cd "$temporary_directory" && sha256sum --check --strict - >/dev/null) \
    || fail "the portable archive checksum is invalid"

  local install_root bin_directory install_directory
  case "${RVS_INSTALL_SCOPE:-user}" in
    user)
      [[ -n "${HOME:-}" ]] || fail "HOME must be set for a user installation"
      install_root="${RVS_INSTALL_ROOT:-${HOME}/.local/share/rvs}"
      bin_directory="${RVS_INSTALL_BIN_DIR:-${HOME}/.local/bin}"
      ;;
    system)
      install_root="${RVS_INSTALL_ROOT:-/opt/rvs}"
      bin_directory="${RVS_INSTALL_BIN_DIR:-/usr/local/bin}"
      ;;
    *) fail "RVS_INSTALL_SCOPE must be user or system" ;;
  esac
  install_directory="${install_root}/${release_version}"
  [[ "$install_root" == /* && "$install_root" != "/" ]] \
    || fail "RVS_INSTALL_ROOT must be an absolute directory other than /"
  [[ "$bin_directory" == /* && "$bin_directory" != "/" ]] \
    || fail "RVS_INSTALL_BIN_DIR must be an absolute directory other than /"
  if [[ -e "$install_directory" && "$repair" != "1" ]]; then
    fail "${install_directory} already exists; rerun with RVS_INSTALL_REPAIR=1 to replace it"
  fi

  local extracted="${temporary_directory}/extracted"
  mkdir -p "$extracted"
  local archive_prefix="rvs-v${release_version}-linux-${architecture}"
  while IFS= read -r member; do
    case "$member" in
      "$archive_prefix" | "$archive_prefix"/*) ;;
      *) fail "the portable archive contains a path outside its release directory" ;;
    esac
    case "/${member}/" in
      */../* | */./*) fail "the portable archive contains an unsafe path" ;;
    esac
  done < <(tar -tzf "${temporary_directory}/${archive_name}")
  tar -xzf "${temporary_directory}/${archive_name}" -C "$extracted"
  local archive_root="${extracted}/${archive_prefix}"
  [[ -x "${archive_root}/rvs" ]] || fail "the portable archive is missing its rvs launcher"

  if [[ "${RVS_INSTALL_SCOPE:-user}" == "system" ]]; then
    as_root install -d -m 0755 "$install_root" "$bin_directory"
    if [[ -e "$install_directory" ]]; then
      as_root rm -rf -- "$install_directory"
    fi
    as_root mv "$archive_root" "$install_directory"
    as_root ln -sfn "${install_directory}/rvs" "${bin_directory}/rvs"
    as_root ln -sfn "${install_directory}/ravenstash" "${bin_directory}/ravenstash"
    as_root ln -sfn "${install_directory}/docker-credential-rvs" "${bin_directory}/docker-credential-rvs"
  else
    install -d -m 0755 "$install_root" "$bin_directory"
    if [[ -e "$install_directory" ]]; then
      rm -rf -- "$install_directory"
    fi
    mv "$archive_root" "$install_directory"
    ln -sfn "${install_directory}/rvs" "${bin_directory}/rvs"
    ln -sfn "${install_directory}/ravenstash" "${bin_directory}/ravenstash"
    ln -sfn "${install_directory}/docker-credential-rvs" "${bin_directory}/docker-credential-rvs"
  fi
  "${bin_directory}/rvs" --version >/dev/null
  say "installed rvs ${release_version} in ${install_directory}"
  if [[ ":${PATH}:" != *":${bin_directory}:"* ]]; then
    say "add ${bin_directory} to PATH"
  fi
}

[[ "$(uname -s)" == "Linux" ]] || fail "this installer currently supports Linux only"
if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
fi
if [[ "${ID:-}" == "nixos" ]]; then
  fail "NixOS needs a native Nix package because standard glibc loader paths are unavailable"
fi

temporary_directory="$(mktemp -d)"
trap 'rm -rf -- "$temporary_directory"' EXIT

if command -v apt-get >/dev/null 2>&1 \
  && command -v dpkg >/dev/null 2>&1 \
  && { [[ -e /etc/debian_version ]] || has_os_family debian || has_os_family ubuntu; }; then
  install_apt_package "$temporary_directory"
else
  install_portable_archive "$temporary_directory"
fi

print_success_banner
say "next: rvs auth login"
