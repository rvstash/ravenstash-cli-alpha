# Platform compatibility policy

Ravenstash treats platform support as an installation, runtime, credential-storage,
update, and native-client contract. The first public release is gated on native
artifacts for the following targets:

| Operating system | Architectures | Artifact and install path |
| --- | --- | --- |
| Linux with glibc 2.28+ | amd64, arm64 | signed APT package and portable archive |
| Linux with musl, including Alpine | amd64, arm64 | signed portable archive |
| macOS 14+ on Apple Silicon; macOS 15+ on Intel | Intel, Apple Silicon | signed and notarized portable archive; `install.sh` |
| Windows 10/11 on x64; Windows 11 on ARM | x64, ARM64 | Authenticode-signed ZIP; `install.ps1` |
| NixOS and Nix on Linux/macOS | x86_64, aarch64 | flake package |
| WSL2 | x86_64, aarch64 | matching Linux path |

The compatibility workflow tests source and frozen executables on native Linux,
macOS, and Windows runners. Alpine artifacts are built and executed in native-architecture
musl containers. CI builds the Nix package on x86-64 Linux; the flake exposes and
evaluates packages for all four Linux/macOS architecture pairs. The release workflow
repeats native builds from one exact source commit, signs macOS and Windows launchers,
notarizes macOS bundles, assembles one checksum inventory, and creates keyless Sigstore
provenance for that complete inventory.

The glibc artifacts are built on Ubuntu 20.04. Portable amd64 smoke coverage includes
Ubuntu 22.04, 24.04, and 26.04; Debian 12 and 13; Fedora 43 and 44; Rocky Linux 8 and
9; AlmaLinux 10; Amazon Linux 2023; openSUSE Leap 15.6 and 16.0; and Arch Linux.
Debian packages are published for both amd64 and arm64 in the same signed channel.

During private alpha, set `RVS_GITHUB_TOKEN` to a read-only token for the private
source repository before running either installer. The token is passed to GitHub's
release API without being placed in a child process argument. The public repository
uses the same artifact names and installers without that variable.

## Credential storage

Interactive login selects an explicit store, a profile preference, the global
preference, or automatic discovery in that order. Automatic discovery tests a
disposable write/read/delete operation before browser authorization.

- macOS uses Keychain and Windows uses Credential Manager through Python Keyring.
- Linux desktops use Secret Service providers such as GNOME Keyring or KWallet.
- POSIX environments may use an initialized `pass` store or the encrypted Ravenstash
  vault. The vault's in-memory session agent uses a protected Unix socket and is not
  offered on Windows.
- `RVS_TOKEN` works without a credential store for CI and other headless use.
- Plaintext storage remains an explicitly acknowledged fallback and is never selected
  automatically.

Release certification covers locked, unlocked, and absent desktop keyrings separately
from headless sessions. Unit tests own provider selection, credential-pair rollback,
refresh locking, vault behavior, and plaintext acknowledgement.

## Managed runtimes and native clients

Python runtime installation selects python-build-standalone assets for Linux glibc,
Linux musl, macOS, and Windows on both architectures. Java selects the corresponding
Temurin build. Node.js supports the official Linux glibc, macOS, and Windows archives,
plus the official x64 musl archive. Node.js does not publish an official ARM64 musl
archive, so Alpine ARM64 users install Node through their system package manager and
`rvs` resolves it from `PATH`.

Native pip, uv, twine, npm, Maven, Docker, Helm, and ORAS wrappers inherit terminal
I/O and use temporary credentials. Windows uses native executable suffixes and command
shims. If Windows policy prevents directory symlinks, the Docker context and plugin
metadata are copied into the temporary overlay instead.

## Update boundaries

APT channels retain the existing compatibility policy: pre-1.0 minor lines and
post-1.0 major lines update independently. Portable, Homebrew, WinGet, and Nix releases
must use the same channel identity and never move a user across it without an explicit
upgrade. Until their package-manager manifests are published, portable users update by
rerunning the same signed installer for their selected channel.

## Additional platforms

FreeBSD, OpenBSD, NetBSD, Linux armv7, and Linux RISC-V remain source-compatible
evaluation targets rather than first-release binary promises. Promoting one requires a
native, repeatable builder, secure credential-store behavior, signed installation and
updates, and the same packaged native-client certification. PyInstaller does not test
those BSD targets upstream, so a successful one-off build is insufficient.

Review this matrix at least quarterly and before changing the Python, PyInstaller,
cryptography, or keyring baselines. A target becomes supported only after its release
artifact and clean-system certification pass.
