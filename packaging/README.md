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
inspection, but published repositories must be signed.
