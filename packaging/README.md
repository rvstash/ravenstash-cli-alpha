# rvs Linux packaging

This directory contains the Linux packaging path for the Ravenstash `rvs` CLI.
The user-facing install paths are a self-contained Debian package and a signed
portable glibc bundle, not a global Python install.

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

After building the `.deb`, generate static APT repository metadata. The channel
is derived from the package version (`0.3.x` -> `v0.3`, `1.x` -> `v1`) and an
explicit override must match that policy:

```bash
RVS_APT_GPG_KEY_ID=<key-id> \
RVS_APT_GPG_FINGERPRINT=<full-fingerprint> \
RVS_APT_CHANNEL=v0.3 \
  packaging/scripts/update-apt-repo.sh
```

Unsigned metadata can be generated without `RVS_APT_GPG_KEY_ID` for local
inspection, but published repositories must be signed. A passphrase-protected
key can be used by setting `RVS_APT_GPG_PASSPHRASE_FILE` to a mode-`0600` file.
The generated repository includes the binary public key
`dist/apt/ravenstash-rvs.gpg`.

Production publishing is owned by this repository. The release workflow
authenticates the prior `InRelease`, every metadata digest, every listed package
digest, and the absence of unlisted pool objects before a separate signing job
sees the tree. A different job uploads immutable pool/by-hash objects first and
`InRelease` last. A twice-weekly split-credential workflow refreshes the
seven-day `Valid-Until`, leaving at least three days between scheduled runs.
The refresh restores the read-only public tree under the signing environment,
passes only bounded signed metadata between jobs, and restores the canonical
tree again under the storage environment. It does not consume GitHub Actions
artifact storage.

APT suites are compatibility boundaries, not rolling maturity labels. Before
`1.0`, every minor series has its own suite (`v0.3`, `v0.4`); from `1.0` onward,
every major series has one (`v1`, `v2`). Routine APT upgrades never cross that
boundary. The legacy `stable` suite remains a permanent alias for `v0.3` so the
initial alpha install cannot later roll into an incompatible release.

The canonical user-facing installer source is `packaging/install.sh`. On a
Debian-family system it verifies the expected signing-key fingerprint,
configures this APT repository, and installs `rvs`. When replacing an older
Ravenstash portable installation, it redirects only the installer-owned links in
`~/.local/bin` to the APT commands so shell `PATH` order cannot keep running the
old release; unrelated files are preserved and reported. On other glibc `amd64`
systems it verifies an OpenPGP-signed release inventory plus the archive's exact
SHA-256 digest and performs a user-local install by default. The same protected
release signer authenticates the APT repository and portable inventory; neither
path accepts unsigned executable bytes. The build includes the installer in the
checksummed and attested release artifacts. After the APT repository and GitHub
release pass their publication gates, the release workflow embeds the exact
attested bytes in a dedicated
Cloudflare Worker at `https://ravenstash.com/install.sh`. The Worker does not
fetch executable shell code from R2, and the frontend website repository
contains no installer implementation.

Source CI builds once on the glibc 2.28 compatibility floor and exercises the
same frozen archive in pinned Ubuntu 22.04/24.04, Debian 12/13, Fedora, Rocky
Linux 8/9, Amazon Linux 2023, and openSUSE Leap containers. Each headless smoke
test verifies normal startup, both aliases, `RVS_TOKEN` authentication, and the
expected no-provider diagnostic without creating a plaintext store. Desktop
keyring behavior is covered separately by provider and disposable round-trip
tests because containers do not supply a real graphical D-Bus session.

Only protected GitHub environments in this repository define these Actions
values:

| Kind | Name | Purpose |
| --- | --- | --- |
| secret | `RVS_APT_GPG_PRIVATE_KEY` | ASCII-armored private signing key |
| secret | `RVS_APT_GPG_PASSPHRASE` | Signing-key passphrase; may be empty |
| secret | `R2_APT_ACCESS_KEY_ID` | Bucket-scoped R2 write credential |
| secret | `R2_APT_SECRET_ACCESS_KEY` | Bucket-scoped R2 write credential |
| variable | `R2_APT_ACCOUNT_ID` | Cloudflare account ID |
| secret | `CLOUDFLARE_API_TOKEN` | Worker-only deployment token |
| variable | `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID |

The secret values must originate in Ravenstash's production Infisical project;
do not commit them or create independent unmanaged copies. The R2 bucket must
be publicly readable through `releases.ravenstash.com` while its S3 write API
remains private. Connecting that custom domain and provisioning the
bucket-scoped token are infrastructure prerequisites, not responsibilities of
this source repository.

The `apt-signing`, `apt-storage`, and `installer-delivery` environments keep
their credentials separated. Releases are manual exact-SHA dispatches. The
built-in token creates a draft against that source commit, populates it once,
and publishes it. The private integration repository has no publishing
credentials and cannot sign, upload, or deploy releases.

The committed public key is an identity pin, not a secret. The private key,
passphrase, R2 credentials, Worker token, and revocation certificate remain in
the production Infisical project. The revocation certificate is deliberately
not copied into GitHub.

See [`RELEASING.md`](../RELEASING.md) for the release and clean-public-import
procedure.
