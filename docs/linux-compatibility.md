# Platform compatibility policy

Ravenstash treats platform support as an installation, runtime, credential-storage,
update, and native-client contract. The first public release is gated on native
artifacts for the following targets:

| Operating system | Architectures | Artifact and install path |
| --- | --- | --- |
| Linux with glibc 2.28+ | amd64, arm64 | signed APT package and portable archive |
| Linux with musl, including Alpine | amd64, arm64 | signed portable archive |
| macOS 14+ on Apple Silicon; macOS 15+ on Intel | Intel, Apple Silicon | checksummed portable archive; `install.sh` |
| Windows 11 | x64, ARM64 | checksummed ZIP; `install.ps1` |
| NixOS and Nix on Linux/macOS | x86_64, aarch64 | flake package |
| WSL2 | x86_64, aarch64 | matching Linux path |

The compatibility workflow tests source and frozen executables on native Linux,
macOS, and Windows runners. Alpine artifacts are built and executed in native-architecture
musl containers. CI builds and executes the Nix package natively for all four
Linux/macOS architecture pairs. One release workflow builds isolated native
artifacts from one exact source commit, assembles one collision-free checksum
inventory, creates keyless Sigstore provenance for that complete inventory, and
publishes those same bytes without rebuilding them.

Passing compatibility CI establishes that the source and release bundles
run on the target hosts. Public support begins only when the exact release artifacts
also pass integrity, installation, and clean-system certification. This prevents an
evaluated Nix output, a smoke-test bundle, or inherited Linux coverage from
being presented as a certified release for Nix, macOS, Windows, or WSL.

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
from headless sessions on real platform credential stores. Unit tests own provider
selection, credential-pair rollback, refresh locking, vault behavior, and plaintext
acknowledgement, but do not replace that host-level certification.

## Managed runtimes and native clients

Python runtime installation selects python-build-standalone assets for Linux glibc,
Linux musl, macOS, and Windows on both architectures. Java selects the corresponding
Temurin build. Node.js supports the official Linux glibc, macOS, and Windows archives.
On every musl system, including Alpine on amd64 and arm64, install Node.js through the
system package manager or another version manager; `rvs` resolves it from `PATH`.

Native pip, uv, twine, npm, Maven, Docker, Helm, and ORAS wrappers inherit terminal
I/O and use temporary credentials. Windows uses native executable suffixes and command
shims. If Windows policy prevents directory symlinks, the Docker context and plugin
metadata are copied into the temporary overlay instead.

The wrappers favor broad compatibility and do not reject a native client because it
is old. `rvs` warns below these advisory versions, then continues the command: pip
23.0, uv 0.4.30, Twine 4.0.2, npm 10.0, Maven 3.9.0, Docker 25.0.2, Helm 3.8.0,
and ORAS 1.1.0. Version detection is best-effort; an unavailable, failed, timed-out,
or unparseable probe does not block execution. The advisory levels identify clients
that predate relevant protocol controls, maintained upstream lines, or security fixes.

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
artifact and clean-system certification pass. Apple notarization and Windows
Authenticode are deferred; their absence must remain explicit in installation and
compatibility documentation.
