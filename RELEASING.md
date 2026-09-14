# Releasing `rvs`

This repository builds every platform artifact in one manually dispatched
release workflow. Stable releases and release candidates share validation,
parallel builds, assembly, attestations, and signing. Only stable releases
publish to APT.

## Release lines

`main` is the next development line. When two minor lines need independent
fixes, create a protected maintenance branch for each supported line:

```text
main                    next development line
release/v0.13           maintained 0.13.x source
release/v0.14           maintained 0.14.x source
release/v1.0            maintained 1.0.x source
release/v1.1            maintained 1.1.x source
```

The matching APT suites are `v0.13`, `v0.14`, `v1.0`, and `v1.1`. Git branches
and APT suites deliberately use the same compatibility identifier, but a branch
holds source while a suite holds immutable signed packages. Patch releases are
tags, not long-lived branches. Delete a maintenance branch only after that line
is no longer supported; its APT objects and tags remain immutable.

Backport a fix with a new pull request targeting the maintenance branch. Use a
cherry-pick followed by a rebase as needed; never merge `main` into a maintenance
branch and never create a merge commit.

## Trust boundaries

Publishing credentials exist only in protected GitHub environments:

| Environment | Credential scope |
| --- | --- |
| `apt-signing` | APT/release inventory signing key |
| `apt-storage` | APT object-storage writer |
| `installer-delivery` | Installer deployment only |

The committed public key and fingerprint are public trust anchors. Private keys,
passphrases, deployment tokens, and revocation material must never be committed.

## Prepare an exact source commit

1. Choose `main` or the owning `release/vMAJOR.MINOR` branch.
2. On a short-lived branch, update `pyproject.toml`, `uv.lock`, both installer
   version/channel constants, and release notes. Keep this as a dedicated final
   version commit.
3. Open a pull request and rebase-merge it after all required gates pass.
4. Run Platform certification manually on the exact protected-branch SHA if it
   has not already passed there.

Do not create a tag manually. The workflow refuses to overwrite an existing tag,
draft, prerelease, release, or APT version.

## Signed release candidate

Use a PEP 440 version such as `0.14.0rc1`. Dispatch `release.yml` from `main`
with `kind=candidate`, the exact source branch, SHA, version, and matching
`vMAJOR.MINOR` channel. The workflow:

- validates all gates for that exact SHA;
- builds the eight release targets in parallel;
- assembles and attests one collision-free inventory;
- signs the checksum inventory with the release OpenPGP key; and
- publishes an immutable GitHub prerelease.

It does not restore, modify, or publish APT repository state. On a supported
Debian-family installation, preview and install it with:

```bash
rvs update --candidate 0.14.0rc1
rvs update --candidate 0.14.0rc1 --apply
```

The CLI downloads the architecture-specific `.deb` and signed inventory,
verifies the signature, checksum, package name, version, and architecture, then
asks before installing. The package uses Debian version `0.14.0~rc1`, ensuring
the later stable `0.14.0` sorts as an upgrade. Other platform bundles remain
available on the GitHub prerelease page.

The candidate command must first ship in a stable CLI version; until then, the
first candidate using this process requires the normal signed manual download.

## Stable release

Use an exact `X.Y.Z` version. Dispatch `release.yml` from `main` with
`kind=stable`, the owning source branch and SHA, and its `vMAJOR.MINOR` channel.
In the same visible workflow run, APT restore runs alongside the platform builds.
After assembly, the workflow signs once, publishes APT in ordered phases,
verifies amd64 and arm64 in parallel, and publishes the GitHub release.

When that stable release should become the default for new installations,
separately dispatch `promote-installer.yml` with the same source identity.
Promotion accepts stable releases only, refuses rollback, deploys the exact
signed installer bytes, and publishes the signed recommended-series manifest.

The scheduled `refresh-apt-metadata` workflow renews expiring APT metadata
without changing packages, tags, channels, or installer recommendations.

## Failure handling

Failed workflows retain short-lived handoff artifacts for diagnosis. Successful
runs remove them. Never repair a partial release by overwriting published bytes;
delete only an unpublished draft after inspection, or issue a new patch/RC
version as appropriate.
