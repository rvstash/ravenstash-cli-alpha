#!/usr/bin/env bash
set -euo pipefail
umask 077

readonly prior_repository="${1:?prior repository path is required}"
readonly deb="${2:?Debian package path is required}"
readonly output_repository="${3:?output repository path is required}"
readonly trusted_keyring="${4:?trusted public keyring is required}"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir

: "${RVS_APT_GPG_KEY_ID:?RVS_APT_GPG_KEY_ID is required}"
: "${RVS_APT_GPG_FINGERPRINT:?RVS_APT_GPG_FINGERPRINT is required}"
: "${RVS_APT_CHANNEL:?RVS_APT_CHANNEL is required}"
readonly promote_channel="${RVS_APT_PROMOTE_CHANNEL:-0}"
[[ "$promote_channel" == "0" || "$promote_channel" == "1" ]]

for command in apt-ftparchive date dpkg-deb find gpg gzip python3 sha256sum; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "error: required command is missing: $command" >&2
    exit 127
  }
done

if compgen -G "$prior_repository/dists/*/InRelease" >/dev/null; then
  python3 "$script_dir/verify_apt.py" "$prior_repository" "$trusted_keyring"
  mkdir -p "$output_repository"
  cp -a "$prior_repository/." "$output_repository/"
else
  test -f "$prior_repository/BOOTSTRAP"
  mkdir -p "$output_repository"
fi

package_name="$(dpkg-deb --field "$deb" Package)"
version="$(dpkg-deb --field "$deb" Version)"
architecture="$(dpkg-deb --field "$deb" Architecture)"
test "$package_name" = "rvs"
[[ "$architecture" == "amd64" || "$architecture" == "arm64" ]]
python3 "$script_dir/channel_policy.py" validate "$version" "$RVS_APT_CHANNEL"

deb_digest="$(sha256sum "$deb" | awk '{print $1}')"
pool="$output_repository/pool/main/r/rvs"
target="$pool/rvs_${version}_${architecture}_${deb_digest:0:16}.deb"
mkdir -p "$pool"
mapfile -t same_version < <(
  find "$pool" -maxdepth 1 -type f -name "rvs_${version}_${architecture}_*.deb" -print
)
for existing in "${same_version[@]}"; do
  if [[ "$existing" != "$target" ]]; then
    echo "error: version $version already exists with a different digest" >&2
    exit 1
  fi
done
if [[ -e "$target" ]]; then
  test "$(sha256sum "$target" | awk '{print $1}')" = "$deb_digest"
else
  install -m 0644 "$deb" "$target"
fi

mapfile -t architectures < <(
  find "$output_repository/pool" -type f -name '*.deb' -print0 \
    | xargs -0 -n1 dpkg-deb --field 2>/dev/null \
    | awk '$1 == "Architecture:" { print $2 }' \
    | sort -u
)
test "${#architectures[@]}" -gt 0
architecture_list="${architectures[*]}"

declare -A distribution_set=()
if [[ -d "$output_repository/dists" ]]; then
  while IFS= read -r distribution; do
    distribution_set["$distribution"]=1
  done < <(
    find "$output_repository/dists" -mindepth 1 -maxdepth 1 -type d -printf '%f\n'
  )
fi
distribution_set["$RVS_APT_CHANNEL"]=1
# The original public alpha used "stable". Keep it forever as a v0.3 alias so
# those installations receive only compatible 0.3.x patches.
if [[ "$RVS_APT_CHANNEL" == "v0.3" || -n "${distribution_set[stable]:-}" ]]; then
  distribution_set[stable]=1
fi
mapfile -t distributions < <(printf '%s\n' "${!distribution_set[@]}" | sort)

actual_fingerprint="$(
  gpg --batch --with-colons --fingerprint "$RVS_APT_GPG_KEY_ID" \
    | awk -F: '$1 == "fpr" { print $10; exit }'
)"
test "$actual_fingerprint" = "$RVS_APT_GPG_FINGERPRINT"
gpg_arguments=(--batch --yes --local-user "$RVS_APT_GPG_KEY_ID" --digest-algo SHA512)
if [[ -n "${RVS_APT_GPG_PASSPHRASE_FILE:-}" ]]; then
  test -f "$RVS_APT_GPG_PASSPHRASE_FILE"
  gpg_arguments+=(--pinentry-mode loopback --passphrase-file "$RVS_APT_GPG_PASSPHRASE_FILE")
fi

valid_until="$(date --utc --date='+7 days' --rfc-email)"
for distribution in "${distributions[@]}"; do
  compatibility_channel="$(
    python3 "$script_dir/channel_policy.py" compatibility-channel "$distribution"
  )"
  for indexed_architecture in "${architectures[@]}"; do
    binary="$output_repository/dists/$distribution/main/binary-${indexed_architecture}"
    mkdir -p "$binary"
    (cd "$output_repository" && apt-ftparchive -a "$indexed_architecture" packages pool) \
      | python3 "$script_dir/channel_policy.py" filter "$compatibility_channel" \
      > "$binary/Packages"
    # A newly supported architecture legitimately has an empty index in older
    # compatibility channels. The repository verifier still requires every
    # distribution to list at least one package across its declared indexes.
    gzip -9n < "$binary/Packages" > "$binary/Packages.gz"
    for index in Packages Packages.gz; do
      index_digest="$(sha256sum "$binary/$index" | awk '{print $1}')"
      by_hash="$binary/by-hash/SHA256/$index_digest"
      mkdir -p "$(dirname "$by_hash")"
      test -e "$by_hash" || install -m 0644 "$binary/$index" "$by_hash"
    done
  done

  config="$output_repository/apt-ftparchive-release-$distribution.conf"
  printf '%s\n' \
    'APT::FTPArchive::Release {' \
    '  Origin "Ravenstash";' \
    '  Label "Ravenstash";' \
    "  Suite \"$distribution\";" \
    "  Codename \"$distribution\";" \
    "  Architectures \"$architecture_list\";" \
    '  Components "main";' \
    '  Description "Ravenstash rvs CLI packages";' \
    '  Acquire-By-Hash "yes";' \
    "  Valid-Until \"$valid_until\";" \
    '};' > "$config"
  rm -f \
    "$output_repository/dists/$distribution/InRelease" \
    "$output_repository/dists/$distribution/Release" \
    "$output_repository/dists/$distribution/Release.gpg"
  release_unsigned="$output_repository/Release-$distribution.unsigned"
  apt-ftparchive -c "$config" release "$output_repository/dists/$distribution" \
    > "$release_unsigned"
  sed "/^Date:/a Valid-Until: $valid_until" "$release_unsigned" \
    | sed "/^Date:/a Ravenstash-Compatibility-Channel: $compatibility_channel" \
    > "$output_repository/dists/$distribution/Release"
  rm -f "$release_unsigned"
  gpg "${gpg_arguments[@]}" \
    --output "$output_repository/dists/$distribution/InRelease" \
    --clearsign "$output_repository/dists/$distribution/Release"
  gpg "${gpg_arguments[@]}" \
    --output "$output_repository/dists/$distribution/Release.gpg" \
    --detach-sign "$output_repository/dists/$distribution/Release"
done
recommended="$(
  python3 "$script_dir/channel_policy.py" existing-recommended \
    "$output_repository" "$RVS_APT_CHANNEL"
)"
if [[ "$promote_channel" == "1" ]]; then
  recommended="$RVS_APT_CHANNEL"
fi
python3 "$script_dir/channel_policy.py" manifest \
  "$output_repository" "$recommended" > "$output_repository/channels.json"
gpg "${gpg_arguments[@]}" \
  --output "$output_repository/channels.json.gpg" \
  --detach-sign "$output_repository/channels.json"
gpg --batch --yes --output "$output_repository/ravenstash-rvs.gpg" \
  --export "$RVS_APT_GPG_KEY_ID"
cmp "$output_repository/ravenstash-rvs.gpg" "$trusted_keyring"
python3 "$script_dir/verify_apt.py" "$output_repository" "$trusted_keyring"
