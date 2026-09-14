# Releasing `rvs`

This repository owns all reviewable source, packaging, signing policy, APT
publication policy, installer delivery code, and GitHub release automation.
The repository remains private during the alpha. The first public beta will be
created as a new `rvstash/ravenstash-cli` repository with one reviewed, clean
initial commit rather than this repository's Git history.

## Trust boundaries

The release jobs use three GitHub environments:

| Environment | Credential scope |
| --- | --- |
| `apt-signing` | APT private key and passphrase only |
| `apt-storage` | Bucket-scoped R2 write key and account ID only |
| `installer-delivery` | Cloudflare Worker deploy token and account ID only |

All secret values originate in the production Infisical path
`/secret-syncs/github/cli-releases`. The offline GPG revocation certificate
stays in Infisical and is never copied into GitHub. The committed public key and
fingerprint are public trust anchors, not credentials.

The private Ravenstash QA repository owns QA, staging, and production smoke
tests and tokens. It has no release credentials. A future GitHub App may
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
   package build. Confirm `platform-ci` passes on the exact release commit for
   native Linux, macOS, and Windows runners, both Alpine architectures, and Nix.
3. Dispatch `.github/workflows/release-candidate.yml` from `dev` with the exact
   40-character commit SHA, exact version, and policy-derived channel. Its eight
   explicitly named target jobs build in parallel and upload only target-specific
   files. Assembly refuses missing or duplicate filenames, creates one checksum
   inventory, and keylessly attests one immutable candidate artifact.
4. Record the successful candidate run ID. After that exact candidate passes the
   required source, platform, certification, release-policy, and real-environment
   gates, dispatch `.github/workflows/release.yml` from `dev` with the candidate
   run ID and the same SHA, version, and channel. Publication authenticates the
   candidate and prior APT state, appends both Debian architectures in one signing
   pass, publishes ordered batched APT phases, verifies amd64 and arm64 in
   parallel, and publishes the GitHub release. A successful publication deletes
   its consumed candidate; failed runs retain their short-lived handoffs for
   diagnosis and retry. Publication refuses any pre-existing tag or release,
   including a partial draft; inspect and resolve such a draft explicitly before
   retrying instead of allowing automation to overwrite it.
5. When the published channel should become the new-install default, separately
   dispatch `.github/workflows/promote-installer.yml`. Promotion authenticates
   the immutable release, refuses rollback, deploys and verifies the exact
   installer bytes, then publishes the signed recommended-channel manifest last.
6. Run the private real-environment smoke workflow for QA and staging. Run the
   production target only by explicit human dispatch.

Do not call a target publicly supported from compatibility CI alone. Before the
first public release, retain evidence that the exact release artifacts were
installed and exercised on clean systems, including real macOS Keychain and
Windows Credential Manager sessions, WSL2, managed runtime downloads, and
representative native package-tool wrappers. Nix must be built and exercised on
each architecture/OS pair claimed by the release. Apple notarization and Windows
Authenticode are deferred, so the command-line installation documentation must
say so explicitly.
Deploy and verify both `https://ravenstash.com/install.sh` and
`https://ravenstash.com/install.ps1` before publishing website copy that directs
users on those platforms to the new release.

The twice-weekly `refresh-apt-metadata` workflow renews the signed seven-day
`Valid-Until` without changing package contents or compatibility channels.

## Clean public import

Before creating `rvstash/ravenstash-cli`, export only the reviewed working tree.
Do not mirror, fork, or push alpha refs. Exclude local caches, generated files,
private integration configuration, and every secret. Search the complete tree
for credentials and internal-only endpoints, run dependency and secret scans,
then create one MIT-licensed initial commit in the empty public repository.

Recreate the three publishing GitHub environments from Infisical, configure
branch and environment protections, enable release immutability, and test a
non-promoted release before switching the installer and APT provenance identity
to the new repository. Historical alpha releases remain in the private alpha
repository; the public repository begins with the first beta release.
