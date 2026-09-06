# Linux compatibility policy

Ravenstash supports Linux as an explicit set of installation, runtime, and
credential-storage contracts. “Linux support” does not mean that one glibc
binary is assumed to work on every kernel, libc, architecture, desktop, and
headless environment.

## Release gates

CLI 0.9.3 is the Artifacts naming transition on the existing `v0.9` installation
channel. Both `art` and `artifacts` remain supported; the hidden `pkg` spelling
expires in 0.9.4. This does not change Linux ABI or credential-storage requirements.

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

Interactive device login resolves credential storage in this order:

1. `--credential-store`, when provided for this login;
2. `RVS_CREDENTIAL_STORE`, when provided by the process;
3. the provider pinned to this profile by its last successful login;
4. the global `rvs auth storage set` preference; and
5. `auto`, which fully tests a working OS keyring, then an initialized `pass`
   store, then an existing encrypted Ravenstash vault.

The OS-keyring adapter uses Python Keyring provider discovery. On Linux this
includes Secret Service implementations such as GNOME Keyring, KWallet Secret
Service, and compatible providers. `pass` is used only when its executable and
initialized password store are both present. A provider is not accepted for
login merely because its library exists: `rvs` performs a disposable
write/read/delete round trip before opening the browser. `rvs auth storage
doctor` performs the same check.

When no provider is usable, the first interactive login stops before browser
authorization and asks yes/no whether to install the dedicated Ravenstash
encrypted vault. After installation, the CLI names the selected store. Advanced
users can still configure another provider with `rvs auth storage setup`. The
Ravenstash vault encrypts all credential entries with AES-256-GCM under a key
derived from the user's passphrase with Argon2id. Its session agent keeps that key only in memory
and exposes a mode-0600, same-UID Unix socket below `XDG_RUNTIME_DIR` (or a
private Ravenstash runtime directory). The agent forgets the key when explicitly
locked or idle for eight hours.
Vault passphrases have an 8-character minimum. The CLI recommends 12+ characters
or a short multi-word passphrase and warns without rejecting lengths from 8 to 11.

Plaintext storage is a supported last resort only after the user types the exact
interactive acknowledgement `STORE PLAINTEXT`, or combines an explicit
`--credential-store plaintext` request with `--allow-insecure-storage` for a
non-interactive setup. It uses a mode-0600 file and prominent warnings, but is
not encrypted and is never considered by `auto` selection.

After authorization, access and refresh credentials are handled as one pair. A
partial write removes both local entries and revokes the newly issued refresh
token. Refresh rotation applies the same rollback rule.

Desktop certification should cover these session states independently:

- GNOME with an unlocked, locked, and absent Secret Service collection;
- KDE Plasma with KWallet Secret Service enabled, locked, and disabled;
- an initialized and uninitialized `pass` store, with and without a usable TTY;
- WSL/server with no session bus;
- both keyring and `pass` present with each explicit preference; and
- encrypted-vault initialization, unlock, lock, idle expiry, passphrase change,
  damaged-file rejection, and atomic credential-pair rollback;
- plaintext setup acknowledgement, unsafe-permission rejection, and proof that
  `auto` never selects it; and
- CI with only `RVS_TOKEN` and no writable home directory assumption beyond CLI
  configuration commands that actually need one.

Unit tests own provider selection, local vault and plaintext-file behavior,
`pass` subprocess safety, disposable round-trip behavior, device-flow preflight,
partial-write rollback, and refresh rollback. A real desktop-session matrix should run in VM-based release
certification; a minimal container is not a faithful substitute for a login
manager, PAM unlock, and the user's D-Bus session.

## Maintenance

Review the matrix at least quarterly and before changing the Python, PyInstaller,
cryptography, or keyring baselines. Add a new distribution major before calling
it supported. Remove a gate only after its upstream security support ends, and
record the change in release notes. Alpine/musl, arm64, and NixOS must remain
visible gaps until their native build and update paths are implemented and
release-tested.
