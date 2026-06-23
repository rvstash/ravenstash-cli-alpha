# rvn Linux packaging

This directory contains the Linux packaging path for the Ravenstash `rvn` CLI.
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

From `packages/rvn/`:

```bash
packaging/scripts/build-pyinstaller.sh
packaging/scripts/build-deb.sh
packaging/scripts/build-tarball.sh
packaging/scripts/build-release-artifacts.sh
```

The generated artifacts are written under `dist/`:

```text
dist/pyinstaller/rvn/              # frozen onedir bundle
dist/packages/rvn_<version>_<arch>.deb
dist/release/rvn-v<version>-linux-<arch>.tar.gz
dist/release/rvn-v<version>-checksums.txt
```

## APT repository

After building the `.deb`, generate static APT repository metadata:

```bash
RVN_APT_GPG_KEY_ID=<key-id> packaging/scripts/update-apt-repo.sh
```

Unsigned metadata can be generated without `RVN_APT_GPG_KEY_ID` for local
inspection, but published repositories must be signed.
