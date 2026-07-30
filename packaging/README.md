# rvs Linux packaging

This directory contains the Linux packaging path for the Ravenstash `rvs` CLI.
The user-facing install path is a self-contained Debian package, not a global
Python install.

## Build tools

Required commands:

```bash
docker
dpkg-deb
apt-ftparchive
gpg
gpgv
sha256sum
```

The canonical build uses `packaging/Dockerfile.ubuntu20`, whose Ubuntu and uv
images are selected by immutable manifest digests. It installs the exact
PyInstaller version from `uv.lock`.

## Local build

From `packages/rvs/`:

```bash
packaging/scripts/build-pyinstaller.sh
packaging/scripts/build-deb.sh
packaging/scripts/build-tarball.sh
packaging/scripts/build-release-artifacts.sh
packaging/scripts/build-in-ubuntu20.sh
```

The generated artifacts are written under `dist/`:

```text
dist/pyinstaller/rvs/              # frozen onedir bundle
dist/packages/rvs_<version>_<arch>.deb
dist/release/rvs-v<version>-linux-<arch>.tar.gz
dist/release/rvs-v<version>-sbom.cdx.json
dist/release/rvs-v<version>-checksums.txt
```

The frozen bundle and Debian package expose both `rvs` and the long-form
`ravenstash` alias. During Debian installation, the post-install script reports
an informational notice when an AMD ROCm Validation Suite `rvs` executable is
present under `/opt/rocm*`.

## APT repository

After building the `.deb`, generate static APT repository metadata:

```bash
RVS_APT_GPG_KEY_ID=<key-id> \
RVS_APT_GPG_FINGERPRINT=<full-fingerprint> \
  packaging/scripts/update-apt-repo.sh
```

Unsigned metadata can be generated without `RVS_APT_GPG_KEY_ID` for local
inspection, but published repositories must be signed. A passphrase-protected
key can be used by setting `RVS_APT_GPG_PASSPHRASE_FILE` to a mode-`0600` file.
The generated repository includes the binary public key
`dist/apt/ravenstash-rvs.gpg`.

Published signing and storage logic does not run here. The private
`rvstash/ravenstash-cli-release` repository authenticates the prior
`InRelease`, every metadata digest, every listed package digest, and the absence
of unlisted pool objects before a separate signing job sees the tree. A
different job uploads immutable pool/by-hash objects first and `InRelease`
last. A daily split-credential workflow refreshes the seven-day `Valid-Until`.

The canonical user-facing installer source is `packaging/install.sh`. It
verifies the expected signing-key fingerprint, configures this APT repository,
and installs `rvs`. The build includes it in the checksummed and attested release
artifacts. The private release orchestrator publishes a digest-addressed copy
and promotes `https://releases.ravenstash.com/rvs/install.sh` only after the APT
repository passes a clean installation check. Cloudflare redirects
`https://ravenstash.com/install.sh` to that release-owned object; the frontend
website repository contains no installer implementation.

Only the private release orchestrator defines these Actions values:

| Kind | Name | Purpose |
| --- | --- | --- |
| secret | `RVS_APT_GPG_PRIVATE_KEY` | ASCII-armored private signing key |
| secret | `RVS_APT_GPG_PASSPHRASE` | Signing-key passphrase; may be empty |
| secret | `R2_APT_ACCESS_KEY_ID` | Bucket-scoped R2 write credential |
| secret | `R2_APT_SECRET_ACCESS_KEY` | Bucket-scoped R2 write credential |
| variable | `R2_APT_ACCOUNT_ID` | Cloudflare account ID |
| secret | `CLI_SOURCE_TOKEN` | Read-only exact-SHA source checkout |

The secret values must originate in Ravenstash's production Infisical project;
do not commit them or create independent unmanaged copies. The R2 bucket must
be publicly readable through `releases.ravenstash.com` while its S3 write API
remains private. Connecting that custom domain and provisioning the
bucket-scoped token are infrastructure prerequisites, not responsibilities of
this source repository.

The source repository contains no QA, staging, production, GPG, R2, or release
token. Releases are manual exact-SHA dispatches. Alpha GitHub releases live in
the private orchestrator, where its built-in token creates a draft, populates it
once, and publishes it under repository release immutability. The eventual
public repository should use a dedicated least-privilege GitHub App for
cross-repository publication.
