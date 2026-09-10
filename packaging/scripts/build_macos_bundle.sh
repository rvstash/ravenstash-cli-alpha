#!/usr/bin/env bash
set -euo pipefail

for variable in \
  RVS_APPLE_CERTIFICATE_BASE64 \
  RVS_APPLE_CERTIFICATE_PASSWORD \
  RVS_APPLE_SIGNING_IDENTITY \
  RVS_APPLE_ID \
  RVS_APPLE_APP_PASSWORD \
  RVS_APPLE_TEAM_ID; do
  [[ -n "${!variable:-}" ]] || {
    echo "error: ${variable} is required" >&2
    exit 1
  }
done

temporary_directory="$(mktemp -d)"
keychain="${temporary_directory}/rvs-signing.keychain-db"
keychain_password="$(openssl rand -hex 24)"
cleanup() {
  security delete-keychain "$keychain" >/dev/null 2>&1 || true
  rm -rf -- "$temporary_directory"
}
trap cleanup EXIT

printf '%s' "$RVS_APPLE_CERTIFICATE_BASE64" \
  | openssl base64 -d -A -out "${temporary_directory}/certificate.p12"
security create-keychain -p "$keychain_password" "$keychain"
security set-keychain-settings -lut 21600 "$keychain"
security unlock-keychain -p "$keychain_password" "$keychain"
security import "${temporary_directory}/certificate.p12" \
  -k "$keychain" -P "$RVS_APPLE_CERTIFICATE_PASSWORD" -T /usr/bin/codesign
security list-keychains -d user -s "$keychain"
security set-key-partition-list -S apple-tool:,apple: -s \
  -k "$keychain_password" "$keychain"

uv sync --frozen --python 3.14 --group release
RVS_CODESIGN_IDENTITY="$RVS_APPLE_SIGNING_IDENTITY" \
  uv run python packaging/scripts/build_portable.py
for launcher in rvs ravenstash docker-credential-rvs; do
  codesign --verify --deep --strict --verbose=2 "dist/pyinstaller/rvs/${launcher}"
done

notarization_archive="${temporary_directory}/rvs-notarization.zip"
ditto -c -k --keepParent dist/pyinstaller/rvs "$notarization_archive"
xcrun notarytool submit "$notarization_archive" \
  --apple-id "$RVS_APPLE_ID" \
  --password "$RVS_APPLE_APP_PASSWORD" \
  --team-id "$RVS_APPLE_TEAM_ID" \
  --wait
