# rvs - Ravenstash Developer CLI

`rvs` is the alpha command line for Ravenstash developer products. It manages
package repositories, authentication, local context, native package workflows,
and developer runtimes; CI remains a future product area.

This work-in-progress alpha is developed privately in
`rvstash/ravenstash-cli-alpha`. The first public beta will start a clean public
history in `rvstash/ravenstash-cli`. The CLI is licensed under the
[MIT License](LICENSE).

## Command Surface

```text
rvs auth       Authenticate a Ravenstash user and manage local credentials
rvs profile    Manage named local CLI profiles
rvs account    Select the acting personal or organization account
rvs context    Inspect the effective user/profile/account/target tuple
rvs shell      Install the visible context prompt integration
rvs runtime    Install and select local Python, Node, and Java runtimes
rvs pkg        Manage Ravenstash package repositories and package workflows
rvs pip        Run pip with ephemeral Ravenstash auth injection
rvs uv         Run uv with ephemeral Ravenstash auth injection
rvs twine      Run twine with ephemeral Ravenstash auth injection
rvs npm        Run npm with ephemeral Ravenstash auth injection
rvs mvn        Run Maven with ephemeral Ravenstash auth injection
rvs repo       Manage Ravenstash package repositories
rvs ci         Placeholder for future Ravenstash CI
rvs update     Check or apply signed APT updates
```

`rvs repo` is the first-class package-repository group. `rvs ci` is registered
but its commands print "not implemented" until that product exists.

Pass global `--json` before a command to emit rvs-owned output as newline-delimited
JSON, for example `rvs --json pkg repo list`. Output from native passthrough tools
remains in the native tool's format.

## Auth

Interactive login uses Ravenstash device authorization:

```bash
rvs auth login
rvs auth login --profile staging
rvs auth login --duration 8h
```

The CLI stores the short-lived CLI access token and profile-scoped refresh token
in the user's selected credential store. In `auto` mode it fully tests a working
OS keyring (Secret Service, including GNOME Keyring, KWallet Secret Service, or
compatible providers), then an initialized `pass` store, then an existing
passphrase-encrypted Ravenstash vault. It never silently selects plaintext.
Local profile metadata lives in `~/.rvs/config.toml`. Automation should pass credentials
with `RVS_TOKEN`; that env var takes precedence over local profiles, requires no
keyring, vault, or D-Bus session, and is never refreshed.

If the first device login finds no usable keyring or `pass` store, it asks whether
to install the dedicated Ravenstash encrypted vault before browser authorization.
The prompt is a simple yes/no choice and names the installed store when setup
finishes. The vault uses Argon2id/AES-GCM and unlocks for the current Linux login
session. An explicitly acknowledged plaintext file remains available through the
advanced storage commands for constrained environments, but it is never an
automatic fallback.

Inspect or select credential storage before logging in:

```bash
rvs auth storage doctor
rvs auth storage setup          # encrypted vault by default
rvs auth storage set auto       # detect an available provider
rvs auth storage set keyring    # use the desktop/system keyring
rvs auth storage set pass       # use the user's initialized pass store
rvs auth storage unlock         # unlock the encrypted vault for this session
rvs auth storage lock
rvs auth login --credential-store pass
```

The provider used by a successful login is pinned to that profile, so a machine
with both desktop keyring and `pass` continues using the user's chosen store.
`RVS_CREDENTIAL_STORE=auto|keyring|pass|vault|plaintext` supplies a non-persistent
override.

Device login discovers and stores the package transfer endpoints returned by
DevAPI. Every control-plane operation goes through DevAPI; `rvs` never calls
Central directly.

Authentication commands operate on the user credential only:

```bash
rvs auth status
rvs auth whoami
rvs auth logout
rvs auth logout --all
```

A local profile is a named CLI configuration containing its DevAPI endpoint,
credential association, discovered repository endpoints, and cached context. It
is not the Ravenstash user or acting account:

```bash
rvs profile list
rvs profile current
rvs profile use work
rvs profile delete work
rvs profile delete --all
rvs profile rename old-name new-name
```

One local profile's authenticated user may access a personal account and several
organizations.
Select the acting account used for authorization, metering, and unqualified target
resolution:

```bash
rvs account list
rvs account current
rvs account use personal
rvs account use org:acme
rvs context current
rvs shell setup
```

Headless automation must make this selection explicitly; device authentication
does not imply a package customer. For a personal account use
`rvs account use personal`. Before selecting an official private mirror,
initialize its remote cache for the selected account once, for example
`rvs pkg mirror add pypiorg`, `rvs pkg mirror add npmjs`, or
`rvs pkg mirror add maven-central`. A `mirror:<source>` request returns 404 until
that binding exists; it is an authorization boundary, not a transient cache miss.

The shell prompt shows `(profile · personal)` or `(profile · org:acme)` and appends
the selected package target. Shell-local profile/account state is non-secret;
tokens remain in the selected credential store.

`rvs auth whoami` verifies the current identity against Ravenstash; it does not
infer identity solely from local profile metadata. `rvs context current` combines
that verified user with the effective local profile, acting account, package
target, and the source of each selection.

## Runtime

Runtime management is limited to local Python, Node, and Java installs:

```bash
rvs runtime install python 3.14
rvs runtime install node 22
rvs runtime install java 21
rvs runtime list
rvs runtime which python 3.14
rvs runtime use python 3.14
rvs runtime env
rvs runtime setup-shell
rvs runtime doctor
```

`rvs runtime use` writes a local version file such as `.python-version`,
`.node-version`, or `.java-version`. The managed shell shims resolve that marker
at invocation time, so changing projects changes the runtime without reinstalling
the shim. Version-prefix selection chooses the newest matching semantic version.

## Package Repositories

Package repository commands are under `rvs pkg`. This area connects the local
machine and native package managers to a remote Ravenstash package repository.

Repository commands:

```bash
rvs pkg repo list
rvs pkg repo list --registry-kind pypi
rvs pkg repo create my-python-packages --registry-kind pypi --default
rvs pkg repo create runtime-images --registry-kind container --default
rvs pkg repo create deployment-charts --registry-kind helm --default
rvs pkg repo show <repo-name>
rvs pkg repo rename <repo-name> <new-name>
rvs pkg repo delete <repo-name>
rvs pkg repo set-default pypi <repo-name>
rvs pkg repo defaults
rvs pkg repo upstream list acme/app pypi
rvs pkg repo upstream add acme/app pypi --private-repository acme/libraries
rvs pkg repo upstream add acme/app pypi --remote-cache pypiorg
rvs pkg repo upstream update acme/app pypi <attachment-id> --min-age-hours 1
rvs pkg repo upstream reorder acme/app pypi <attachment-id> <attachment-id>
rvs pkg repo upstream remove acme/app pypi <attachment-id>

rvs pkg mirror list
rvs pkg mirror create --registry-kind pypi
rvs pkg mirror show <cache-id>
rvs pkg mirror set-age <cache-id> --min-age-hours 24
rvs pkg mirror delete <cache-id>
```

Select one typed target without reserving workspace names:

```bash
rvs pkg select acme/backend
rvs pkg select mirror:pypiorg
rvs pkg select custom-mirror:piwheels
rvs pkg current
rvs pkg clear

rvs pkg --target acme/backend --kind pypi install internal-lib
rvs pkg --target mirror:pypiorg install requests
rvs pkg --target custom-mirror:piwheels --kind pypi install numpy
```

`rvs pkg mirror` manages the private install surface backed by each remote cache.
Official and custom mirrors stay visibly distinct:

```bash
rvs pkg mirror add pypiorg --select
rvs pkg mirror create-custom piwheels --kind pypi \
  --api-url https://www.piwheels.org/simple/ \
  --publication-control externally-controlled --select
rvs pkg mirror select pypiorg
rvs pkg mirror select --custom piwheels
```

A remote cache is a customer-owned read-only binding to a curated or custom
registry. Its private mirror is always available to authorized users with an
independent 24-hour minimum-age default. Connect the remote cache to a repository
with `--remote-cache`; select `mirror:` for direct package-manager use. A private
PyPI, npm, or Maven lane can also attach a same-kind private
lane from the same customer, including another workspace. Private sources expose
only their intrinsic packages; their own upstream plans are never traversed.
Private attachments default to zero/disabled minimum age, while official remote
attachments retain the server recommendation. Container and Helm are private-only.

Repository references use the package repository name, such as
`my-python-packages`. Repository names use lowercase letters, numbers, and
hyphens. When a name is ambiguous across authorized workspaces, use
`<workspace>/<repo-name>` or pass `--customer-id`. After resolving the target,
the CLI always builds native package URLs from the immutable
`<workspace_unique_ref>/<repository_unique_ref>` pair.

The acting account and selected target are scoped by local profile and immutable
customer ID. Legacy per-kind repository defaults remain readable as a migration
fallback. An explicit `--target` is one-shot and never changes saved state.

Saved defaults store immutable workspace and repository references as identity
and keep names only as display hints. A later workspace or repository rename
therefore requires no local migration: list and resolve calls return the current
name while native URLs continue using the same stable references. Remote-cache
commands use immutable public cache IDs returned by DevAPI and do not persist a
mutable cache name as local identity.

Saved customer defaults also retain the current organization role and member
authority revision. If refresh or resolution reports that an immutable target
was removed or is no longer assigned, `rvs` preserves that target identity but
marks it unavailable. It never rebinds the profile to a same-named object and
never retries another customer credential after an authorization failure.

Package metadata commands:

```bash
rvs pkg package list --repo <repo-name> --registry-kind pypi
rvs pkg package show requests --repo <repo-name> --registry-kind pypi
rvs pkg package delete requests --repo <repo-name>
rvs pkg package delete-version requests 2.32.0 --repo <repo-name>
rvs pkg package yank requests 2.32.0 --repo <repo-name> --reason "bad build"
```

PyPI helpers:

```bash
rvs pkg pypi index-url --repo <repo-name>
rvs pkg pypi upload-url --repo <repo-name>
rvs pkg pypi install requests --repo <repo-name>
rvs pkg pypi publish dist/ --repo <repo-name>
rvs pkg pypi configure --repo <repo-name>
```

The install helper sets Ravenstash as pip's primary `PIP_INDEX_URL`; it does not
add a second index that could silently win dependency resolution.

npm helpers:

```bash
rvs pkg npm registry-url --repo <repo-name>
rvs pkg npm npmrc --repo <repo-name>
rvs pkg npm install lodash --repo <repo-name>
rvs pkg npm publish . --repo <repo-name>
rvs pkg npm configure --repo <repo-name>
```

Direct npm publishing uses native `npm pack` before sending the wire payload, so
npm packlists, lifecycle hooks, bundled dependencies, and generated files are
honored. An `npm` executable is required.

Maven helpers:

```bash
rvs pkg maven repo-url --repo <repo-name>
rvs pkg maven settings --repo <repo-name>
rvs pkg maven install com.example:lib:1.0.0 --repo <repo-name>
rvs pkg maven deploy ./target/lib.jar --group com.example --artifact lib --version 1.0.0 --repo <repo-name>
rvs pkg maven configure --repo <repo-name>
```

Package-token management is intentionally not part of the alpha CLI surface.

Native package-manager wrappers:

```bash
rvs pip install acme-utils
rvs uv sync
rvs twine upload dist/*
rvs npm install @acme/widgets
rvs mvn test
rvs docker --rvs-target acme/runtime-images pull oci.rvsta.sh/acme/runtime-images/api:latest
rvs helm --rvs-target acme/deployment-charts show chart oci://oci.rvsta.sh/acme/deployment-charts/charts/api --version 1.2.3
rvs oras --rvs-kind container --rvs-target acme/runtime-images discover oci.rvsta.sh/acme/runtime-images/api:latest
rvs oci-reference --kind container --target acme/runtime-images --oci-path api --reference latest

rvs npm --rvs-target acme/my-node-packages install @acme/widgets
rvs pip --rvs-target acme/my-python-packages install acme-utils
rvs uv --rvs-target acme/my-python-packages --rvs-native-config isolate sync
```

`rvs pkg ...` is Ravenstash-native: it selects a typed Ravenstash target through
`--target` or the effective local-profile/acting-account context, and the underlying implementation may or may
not use a native package manager. `rvs pip`, `rvs uv`, `rvs twine`, `rvs npm`,
`rvs mvn`, `rvs docker`, `rvs helm`, and `rvs oras` are explicit native-tool passthroughs. The
package-release wrappers respect native config
by default, detect Ravenstash registry URLs, and inject only short-lived
credentials for the child process. They do not write tokens to `.npmrc`,
`pip.conf`, `.pypirc`, `settings.xml`, `pyproject.toml`, or `uv.toml`.
The controlling `RVS_TOKEN`, when present, is removed from every launched native
process after the scoped package capability has been exchanged. Temporary netrc,
Maven settings, OCI config, and OCI broker files are removed when the wrapper exits.

The registry protocol supports a broader native-client compatibility matrix than
the passthrough command list. Poetry; Yarn, pnpm, and Bun; Gradle and sbt; and
Podman, nerdctl, Skopeo, and Crane use their own native configuration with an
`RVS_TOKEN`; there are no corresponding `rvs <tool>` passthroughs yet. A catalog
client association means protocol compatibility, not the existence of an RVS
wrapper.

The OCI wrappers resolve one exact Container or Helm lane, request a scoped
capability, and overlay an ephemeral `docker-credential-rvs` entry on a copy of
the native registry config. Existing credentials for other registries are
preserved; stale Ravenstash auth entries are removed from the copy. The token is
never placed in argv or written to the user's Docker or Helm config. Docker,
Helm, and ORAS all use the same `oci.rvsta.sh` host and the stable
`/<workspace-ref>/<repository-ref>/...` namespace. `rvs oras` requires
`--rvs-kind container` or `--rvs-kind helm` because ORAS supports both lanes.

## Installation on Linux / WSL

The supported end-user install path is a signed self-contained distribution,
not `pip install`. The CLI embeds Python 3.14; it does not use the system Python.
User config, credentials, and managed runtimes stay in `~/.rvs`.

Install the current recommended Linux compatibility channel:

```bash
curl -fsSL https://ravenstash.com/install.sh | bash
```

On Debian, Ubuntu, WSL, and derivatives such as Linux Mint and Pop!_OS, the
installer verifies the published APT signing-key fingerprint, configures the
signed Ravenstash APT channel, and installs the system package. On other
`amd64` distributions with glibc 2.28 or newer—including current Fedora,
RHEL-compatible, Amazon Linux, and openSUSE systems—it verifies a detached
OpenPGP signature and exact SHA-256 digest before installing the portable bundle
under `~/.local/share/rvs` and linking commands into `~/.local/bin`.

The current portable artifact is `amd64`/glibc only. Linux `arm64` and
Alpine/musl are detected and rejected with an explicit diagnostic rather than
attempting to execute an incompatible binary. They remain release-matrix gaps,
not claimed support. Review the installer source at
<https://ravenstash.com/install.sh> before running it if required by your
environment. Set `RVS_INSTALL_SCOPE=system` for `/opt/rvs` plus
`/usr/local/bin`; the default portable install is rootless and per-user.

Direct `.deb` artifacts are also published for early testing:

```bash
sudo apt install ./rvs_<version>_amd64.deb
```

APT remains the update authority for Debian-family package installs:

```bash
rvs update                 # check compatible updates in the current channel
rvs update --apply         # refresh APT metadata and install a compatible update
rvs upgrade --to 0.7       # explicitly accept the current compatibility channel
sudo apt upgrade           # updates only within the configured channel
```

Before `1.0`, each `v0.Y` APT suite is a compatibility boundary: `0.Y.Z`
patches may update normally, while moving to another minor channel is explicit.
Starting with `1.0`, the major version is the boundary (`v1`, `v2`, and so on).
The CLI authenticates the signed channel manifest before offering or applying a
channel change. It never downloads over and replaces its own executable.

Portable installations are updated by rerunning the signed installer. The
current `rvs update` and `rvs upgrade` commands deliberately modify only a
recognized Ravenstash APT installation.

WSL/headless/server note: `RVS_TOKEN` works without extra setup and is the
recommended CI path. Interactive WSL users without Secret Service or `pass` can
use the encrypted Ravenstash vault; its passphrase is requested on creation and
once after the vault agent is lost, locked, or idle for eight hours. Run
`rvs auth storage doctor` before login to see exactly what this session can use.
Vault passphrases require 8 characters; 12+ characters or a short multi-word
passphrase is recommended, and shorter accepted passphrases display a warning.

## Release packaging

Linux package scaffolding lives under `packaging/`. From this folder:

```bash
packaging/scripts/build-release-artifacts.sh
```

The canonical compatibility build runs inside the pinned Ubuntu 20.04 builder:

```bash
packaging/scripts/build-in-ubuntu20.sh
```

That builds the Python 3.14 PyInstaller bundle, Debian package, tarball,
CycloneDX SBOM, and checksum file.
See [`docs/linux-compatibility.md`](docs/linux-compatibility.md) for the distro,
installer, headless, desktop-keyring, and known-gap release matrix.
APT repository metadata is generated and signed separately:

```bash
RVS_APT_GPG_KEY_ID=<key-id> packaging/scripts/update-apt-repo.sh
```

This private alpha repository owns the complete, reviewable packaging and
release policy. Exact approved commits are rebuilt, attested, signed, installed
on Ubuntu 20.04, and published through split GitHub environments. Real DevAPI
integration tests remain in a separate private repository with no publishing
credentials. See [`packaging/README.md`](packaging/README.md) and
[`RELEASING.md`](RELEASING.md) for the trust boundaries and release procedure.

## Local Development

Use the package venv directly from this folder:

```bash
cd packages/rvs
uv sync --python 3.14
source .venv/bin/activate
rvs --help
```

Run checks from `packages/rvs/`:

```bash
.venv/bin/pytest
.venv/bin/ruff check rvs tests
```

## Layout

```text
rvs/
├── cli.py
├── auth/
├── runtime/
├── pkg/
│   └── registries/
├── repo/
├── ci/
├── client.py
├── config.py
└── output.py
```
