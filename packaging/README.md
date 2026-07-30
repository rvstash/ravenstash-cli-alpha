# rvs Linux packaging

This directory contains the Linux packaging path for the Ravenstash `rvs` CLI.
The user-facing install path is a self-contained Debian package, not a global
Python install.

## Build tools

Required commands:

```bash
pyinstaller
nfpm
apt-ftparchive
gpg
sha256sum
```

`apt-ftparchive`, `gpg`, and `sha256sum` are normally provided by Ubuntu system
packages. `pyinstaller` and `nfpm` are installed by the release workflow.

## Local build

From `packages/rvs/`:

```bash
packaging/scripts/build-pyinstaller.sh
packaging/scripts/build-deb.sh
packaging/scripts/build-tarball.sh
packaging/scripts/build-release-artifacts.sh
```

The generated artifacts are written under `dist/`:

```text
dist/pyinstaller/rvs/              # frozen onedir bundle
dist/packages/rvs_<version>_<arch>.deb
dist/release/rvs-v<version>-linux-<arch>.tar.gz
dist/release/rvs-v<version>-checksums.txt
```

The frozen bundle and Debian package expose both `rvs` and the long-form
`ravenstash` alias. During Debian installation, the post-install script reports
an informational notice when an AMD ROCm Validation Suite `rvs` executable is
present under `/opt/rocm*`.

## APT repository

After building the `.deb`, generate static APT repository metadata:

```bash
RVS_APT_GPG_KEY_ID=<key-id> packaging/scripts/update-apt-repo.sh
```

Unsigned metadata can be generated without `RVS_APT_GPG_KEY_ID` for local
inspection, but published repositories must be signed. A passphrase-protected
key can be used by setting `RVS_APT_GPG_PASSPHRASE_FILE` to a mode-`0600` file.
The generated repository includes the binary public key
`dist/apt/ravenstash-rvs.gpg`.

The tag release workflow publishes this static repository to the
`rvs/apt/` prefix of a Cloudflare R2 bucket. It first downloads the existing
prefix so old package versions remain available, then uploads package objects
before replacing the signed indexes.

The private alpha repository must define these repository-level Actions values:

| Kind | Name | Purpose |
| --- | --- | --- |
| secret | `RVS_APT_GPG_PRIVATE_KEY` | ASCII-armored private signing key |
| secret | `RVS_APT_GPG_PASSPHRASE` | Signing-key passphrase; may be empty |
| secret | `R2_APT_ACCESS_KEY_ID` | Bucket-scoped R2 write credential |
| secret | `R2_APT_SECRET_ACCESS_KEY` | Bucket-scoped R2 write credential |
| variable | `R2_APT_ACCOUNT_ID` | Cloudflare account ID |
| variable | `R2_APT_BUCKET` | APT release bucket name |

The secret values must originate in Ravenstash's production Infisical project;
do not commit them or create independent unmanaged copies. The R2 bucket must
be publicly readable through `downloads.ravenstash.com` while its S3 write API
remains private. Connecting that custom domain and provisioning the
bucket-scoped token are infrastructure prerequisites, not responsibilities of
this source repository.

GitHub Free does not provide deployment environments to private organization
repositories, so the alpha uses tag-gated repository secrets. When the clean
public `ravenstash-cli` repository is created for beta, move these values into a
protected `release` environment and add that environment back to the publish
job.
