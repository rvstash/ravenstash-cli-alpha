# rvs release packaging

This directory contains the cross-platform packaging path for the Ravenstash
`rvs` CLI. User-facing installs use self-contained native bundles, signed APT
packages, or the Nix flake rather than a global Python install.

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
dist/release/rvs-v<version>-linux-musl-<arch>.tar.gz
dist/release/rvs-v<version>-macos-<arch>.tar.gz
dist/release/rvs-v<version>-windows-<arch>.zip
dist/release/rvs-v<version>-sbom.cdx.json
dist/release/rvs-v<version>-checksums.txt
dist/release/rvs-v<version>-package-manifests.tar.gz
```

The frozen bundle and Debian package expose both `rvs` and the long-form
`ravenstash` alias. During Debian installation, the post-install script reports
an informational notice when an AMD ROCm Validation Suite `rvs` executable is
present under `/opt/rocm*`.

Native symbols are stripped from Linux and macOS release bundles. Windows
bundles omit the encrypted-vault `cryptography` dependency because that vault
is unavailable on Windows; Windows credentials use Credential Manager instead.

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

Production publishing is owned by this repository. A candidate workflow builds
eight isolated native targets in parallel, rejects filename collisions during
assembly, and attests one immutable inventory. The publication workflow consumes
that exact candidate by run ID; it does not rebuild release artifacts. It
authenticates the prior `InRelease`, every metadata digest, every listed package
digest, and the absence of unlisted pool objects before a separate signing job
sees the tree. Both Debian architectures are appended before one index-generation
and signing pass. A different job batches immutable pool/by-hash objects first,
then mutable indexes and releases, with `InRelease` and channel discovery last.
If an interrupted older publish omitted an architecture's indexes, the
storage-side restore may reconstruct only bytes that exactly match the
already-authenticated `InRelease` SHA-256 inventory; any mismatch remains a hard
failure. A twice-weekly split-credential workflow refreshes the
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

Published suites contain separate `amd64` and `arm64` indexes. Immutable pool
filenames carry a digest suffix, so index generation filters the package's
declared architecture from its metadata instead of relying on Debian filename
conventions. A newly added architecture may have an empty index in an older
compatibility suite, while every suite must retain at least one valid package.

The POSIX user-facing installer source is `packaging/install.sh`; the Windows
source is `packaging/install.ps1`. On a Debian-family system the shell installer
verifies the expected signing-key fingerprint,
configures this APT repository, and installs `rvs`. When replacing an older
Ravenstash portable installation, it redirects only the installer-owned links in
`~/.local/bin` to the APT commands so shell `PATH` order cannot keep running the
old release; unrelated files are preserved and reported. On Linux glibc, Linux
musl, and macOS for amd64 or arm64 it verifies an OpenPGP-signed release inventory
plus the archive's exact SHA-256 digest and performs a user-local install by default.
The PowerShell installer selects Windows x64 or ARM64, verifies the release digest,
installs per-user by default, and updates user `PATH`. Apple notarization and
Windows Authenticode are deferred while these platforms use command-line
distribution. The protected APT signer authenticates the APT repository and POSIX
portable inventory. The build includes the installer in the
checksummed and attested release artifacts. After the APT repository and GitHub
release pass their publication gates, the separate promotion workflow embeds the
exact attested bytes in a dedicated
Cloudflare Worker at `https://ravenstash.com/install.sh` and
`https://ravenstash.com/install.ps1`. The Worker does not
fetch executable shell code from R2, and the frontend website repository
contains no installer implementation. The promotion workflow separately checks
out the immutable release source, refuses installer rollback, deploys only bytes
that match the release's signed inventory, verifies the live routes, and
publishes the newly signed recommended-channel manifest last.

Source CI builds on native Linux amd64/arm64, macOS Intel/Apple Silicon, and
Windows x64/ARM64 runners. Alpine musl builds run on both native architectures.
The glibc 2.28 compatibility build also exercises the
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
and publishes it. The Ravenstash QA repository has no publishing
credentials and cannot sign, upload, or deploy releases.

The committed public key is an identity pin, not a secret. The private key,
passphrase, R2 credentials, Worker token, and revocation certificate remain in
the production Infisical project. The revocation certificate is deliberately
not copied into GitHub.

See [`RELEASING.md`](../RELEASING.md) for the release and clean-public-import
procedure.
