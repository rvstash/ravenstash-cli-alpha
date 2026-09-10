# Releasing `rvs`

This repository owns all reviewable source, packaging, signing policy, APT
publication policy, installer delivery code, and GitHub release automation.
The repository remains private during the alpha. The first public beta will be
created as a new `rvstash/ravenstash-cli` repository with one reviewed, clean
initial commit rather than this repository's Git history.

## Trust boundaries

The release jobs use five GitHub environments:

| Environment | Credential scope |
| --- | --- |
| `macos-signing` | Apple signing and notarization credentials only |
| `windows-signing` | Windows Authenticode credentials only |
| `apt-signing` | APT private key and passphrase only |
| `apt-storage` | Bucket-scoped R2 write key and account ID only |
| `installer-delivery` | Cloudflare Worker deploy token and account ID only |

All secret values originate in the production Infisical path
`/secret-syncs/github/cli-releases`. The offline GPG revocation certificate
stays in Infisical and is never copied into GitHub. The committed public key and
fingerprint are public trust anchors, not credentials.

The separate private integration repository owns QA, staging, and production
smoke tests and tokens. It has no release credentials. A future GitHub App may
report an integration result back to this repository, but integration tests do
not gate a release by holding a publisher token.

## Compatibility policy

- Before 1.0, each minor line has its own APT channel: `0.4.x` uses `v0.4`.
- Starting at 1.0, each major line has its own channel: `1.x` uses `v1`.
- Patch upgrades stay automatic within the installed channel.
- Crossing a compatibility boundary is explicit through `rvs upgrade --to`.
- A release version and every APT object are immutable. Fixes receive a new
  patch version; the repository is never reset or rewritten.

## Alpha release procedure

1. Update `pyproject.toml`, `uv.lock`, `packaging/install.sh`,
   `packaging/install.ps1`, release notes, and any compatibility documentation
   in one reviewed commit on `dev`.
2. Run the local checks documented in `AGENTS.md` plus the pinned Ubuntu 20.04
   package build.
3. Dispatch `.github/workflows/release.yml` from `dev` with the exact 40-character
   commit SHA, exact version, and policy-derived channel. Set `promote_channel`
   only when new installations should select that channel.
4. The workflow proves the commit is on `dev`; builds Linux glibc, Linux musl,
   macOS, and Windows artifacts for amd64/arm64; signs and notarizes the desktop
   bundles; and attests the complete inventory. It restores and verifies the
   entire signed APT tree, publishes `InRelease` last, installs both Debian
   architectures, optionally deploys the exact attested installer bytes, and
   publishes the GitHub release against the source commit.
5. Run the private real-environment smoke workflow for QA and staging. Run the
   production target only by explicit human dispatch.

The daily `refresh-apt-metadata` workflow renews the signed seven-day
`Valid-Until` without changing package contents or compatibility channels.

## Clean public import

Before creating `rvstash/ravenstash-cli`, export only the reviewed working tree.
Do not mirror, fork, or push alpha refs. Exclude local caches, generated files,
private integration configuration, and every secret. Search the complete tree
for credentials and internal-only endpoints, run dependency and secret scans,
then create one MIT-licensed initial commit in the empty public repository.

Recreate the five GitHub environments from Infisical, configure branch and
environment protections, enable release immutability, and test a non-promoted
release before switching the installer and APT provenance identity to the new
repository. Historical alpha releases remain in the private alpha repository;
the public repository begins with the first beta release.
