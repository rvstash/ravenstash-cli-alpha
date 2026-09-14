#!/usr/bin/env bash
set -euo pipefail

readonly repository="${1:?repository path is required}"
readonly endpoint="${2:?R2 endpoint is required}"
readonly bucket="${3:?R2 bucket is required}"
readonly destination="s3://${bucket}/rvs/apt"

mapfile -t distributions < <(
  find "$repository/dists" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort
)
test "${#distributions[@]}" -gt 0

# Upload immutable package and by-hash objects first.
aws s3 sync "$repository/pool/" "${destination}/pool/" \
  --endpoint-url "$endpoint" \
  --cache-control "public,max-age=31536000,immutable" \
  --no-progress
for distribution in "${distributions[@]}"; do
  mapfile -t binary_directories < <(
    find "$repository/dists/$distribution/main" \
      -mindepth 1 -maxdepth 1 -type d -name 'binary-*' -print | sort
  )
  test "${#binary_directories[@]}" -gt 0
  for binary_directory in "${binary_directories[@]}"; do
    architecture_directory="${binary_directory##*/}"
    aws s3 sync \
      "$binary_directory/by-hash/" \
      "${destination}/dists/$distribution/main/${architecture_directory}/by-hash/" \
      --endpoint-url "$endpoint" \
      --cache-control "public,max-age=31536000,immutable" \
      --no-progress
  done
done

# Mutable indexes follow. Each signed distribution becomes active only when its
# InRelease lands, and channel discovery becomes active last.
aws s3 cp "$repository/ravenstash-rvs.gpg" "${destination}/ravenstash-rvs.gpg" \
  --endpoint-url "$endpoint" \
  --cache-control "no-cache" \
  --only-show-errors
for distribution in "${distributions[@]}"; do
  mapfile -t binary_directories < <(
    find "$repository/dists/$distribution/main" \
      -mindepth 1 -maxdepth 1 -type d -name 'binary-*' -print | sort
  )
  for binary_directory in "${binary_directories[@]}"; do
    architecture_directory="${binary_directory##*/}"
    for index in Packages Packages.gz; do
      relative="main/${architecture_directory}/${index}"
      aws s3 cp \
        "$repository/dists/$distribution/$relative" \
        "${destination}/dists/$distribution/$relative" \
        --endpoint-url "$endpoint" \
        --cache-control "no-cache" \
        --only-show-errors
    done
  done
  for relative in Release Release.gpg; do
    aws s3 cp \
      "$repository/dists/$distribution/$relative" \
      "${destination}/dists/$distribution/$relative" \
      --endpoint-url "$endpoint" \
      --cache-control "no-cache" \
      --only-show-errors
  done
done
for distribution in "${distributions[@]}"; do
  aws s3 cp \
    "$repository/dists/$distribution/InRelease" \
    "${destination}/dists/$distribution/InRelease" \
    --endpoint-url "$endpoint" \
    --cache-control "no-cache" \
    --only-show-errors
done
for object in channels.json channels.json.gpg; do
  aws s3 cp "$repository/$object" "${destination}/$object" \
    --endpoint-url "$endpoint" \
    --cache-control "no-cache" \
    --only-show-errors
done
