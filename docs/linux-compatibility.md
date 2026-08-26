# Linux compatibility policy

Ravenstash supports Linux as an explicit set of installation, runtime, and
credential-storage contracts. “Linux support” does not mean that one glibc
binary is assumed to work on every kernel, libc, architecture, desktop, and
headless environment.

## Release gates

The glibc `amd64` bundle is built on Ubuntu 20.04 (glibc 2.31) and declares a
glibc 2.28 runtime floor. Every source change runs that exact frozen archive in
immutable container images for:

- Ubuntu 22.04, 24.04, and 26.04;
- Debian 12 and 13;
- Fedora 43 and 44;
- Rocky Linux 8 and 9, plus AlmaLinux 10 as the RHEL-compatible major-10 gate;
- Amazon Linux 2023;
- openSUSE Leap 15.6 and 16.0; and
- current Arch Linux.

Ubuntu 20.04 additionally installs and exercises the generated Debian package.
The matrix intentionally includes the long-lived oldest ABI floor as well as
supported releases from the preceding four years. Fast-moving distributions
that have reached end of life are not retained as security-support claims.

The runtime smoke checks the `rvs` and `ravenstash` entry points, the Docker
credential helper, CLI startup/help, `RVS_TOKEN` in a headless environment, and
the absence of an accidental plaintext credential fallback.

## Installer selection

| Environment | Selected path | Privilege model |
| --- | --- | --- |
| Debian/Ubuntu/WSL and `ID_LIKE` derivatives | Signed APT channel | root or `sudo` |
| Other `amd64` distributions with glibc 2.28+ | Signed portable archive | user-local by default |
| Minimal RPM/openSUSE/Arch system | Portable archive after package-manager provisioning of verification tools | user-local CLI; root only for missing prerequisites |
| CI or ephemeral server | Either install path plus `RVS_TOKEN` | no credential store required |
| Alpine or another musl system | Explicit unsupported diagnostic | separate musl artifact required |
| Linux `arm64` | Explicit unsupported diagnostic | native arm64 build required |
| NixOS | Explicit unsupported diagnostic | native Nix packaging required |

The portable path verifies the pinned Ravenstash OpenPGP key fingerprint, the
detached signature over the release checksum inventory, the selected archive's
exact SHA-256 digest, and the archive's top-level path boundary before moving
the bundle into its final directory.

## Credential-provider selection

Interactive device login never stores credentials as plaintext. Resolution is:

1. `--credential-store`, when provided for this login;
2. `RVS_CREDENTIAL_STORE`, when provided by the process;
3. the provider pinned to this profile by its last successful login;
4. the global `rvs auth keyring set` preference; and
5. `auto`, which chooses a working OS keyring, then an initialized `pass` store.

The OS-keyring adapter uses Python Keyring provider discovery. On Linux this
includes Secret Service implementations such as GNOME Keyring, KWallet Secret
Service, and compatible providers. `pass` is used only when its executable and
initialized password store are both present. A provider is not accepted for
login merely because its library exists: `rvs` performs a disposable
write/read/delete round trip before opening the browser. `rvs auth keyring
doctor` performs the same check.

After authorization, access and refresh credentials are handled as one pair. A
partial write removes both local entries and revokes the newly issued refresh
token. Refresh rotation applies the same rollback rule.

Desktop certification should cover these session states independently:

- GNOME with an unlocked, locked, and absent Secret Service collection;
- KDE Plasma with KWallet Secret Service enabled, locked, and disabled;
- an initialized and uninitialized `pass` store, with and without a usable TTY;
- WSL/server with no session bus;
- both keyring and `pass` present with each explicit preference; and
- CI with only `RVS_TOKEN` and no writable home directory assumption beyond CLI
  configuration commands that actually need one.

Unit tests own provider selection, `pass` subprocess safety, disposable
round-trip behavior, device-flow preflight, partial-write rollback, and refresh
rollback. A real desktop-session matrix should run in VM-based release
certification; a minimal container is not a faithful substitute for a login
manager, PAM unlock, and the user's D-Bus session.

## Maintenance

Review the matrix at least quarterly and before changing the Python, PyInstaller,
cryptography, or keyring baselines. Add a new distribution major before calling
it supported. Remove a gate only after its upstream security support ends, and
record the change in release notes. Alpine/musl, arm64, and NixOS must remain
visible gaps until their native build and update paths are implemented and
release-tested.
