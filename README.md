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
rvs runtime    Install and select local Python, Node, and Java runtimes
rvs art        Manage repositories for packages, container images, and Helm charts
rvs artifacts  Full-name alias of rvs art
rvs pip        Run pip with ephemeral Ravenstash auth injection
rvs uv         Run uv with ephemeral Ravenstash auth injection
rvs twine      Run twine with ephemeral Ravenstash auth injection
rvs npm        Run npm with ephemeral Ravenstash auth injection
rvs mvn        Run Maven with ephemeral Ravenstash auth injection
rvs ci         Placeholder for future Ravenstash CI
rvs update     Check or apply signed APT updates
```

`rvs art repo` and `rvs artifacts repo` provide repository management. `rvs ci` is registered
but its commands print "not implemented" until that product exists.

Both Artifacts spellings support identical options and output. Use `rvs art` or
`rvs artifacts`; the former temporary product spelling is unsupported. There is
no top-level `rvs repo`. Existing config version 3,
profile-scoped credentials, account IDs, and `selected_target` records continue
to work without an identity or credential-store migration.

Pass global `--json` before a command to emit rvs-owned output as newline-delimited
JSON, for example `rvs --json art repo list`. Output from native passthrough tools
remains in the native tool's format.

## Auth

Interactive login uses Ravenstash device authorization:

```bash
rvs auth login
rvs auth login --profile staging
rvs auth login --duration 12h
```

Device sessions last 180 days by default. Use `--duration` to request a shorter
session from 12 hours through 180 days.

The CLI stores the short-lived CLI access token and profile-scoped refresh token
in the user's selected credential store. In `auto` mode it fully tests a working
OS keyring (Secret Service, including GNOME Keyring, KWallet Secret Service, or
compatible providers), then an initialized `pass` store, then an existing
passphrase-encrypted Ravenstash vault. It never silently selects plaintext.
Local profile metadata lives in `~/.rvs/config.toml`. The file carries an internal
schema version; a newer CLI applies every skipped migration in order and atomically
persists the result only after the migrated configuration validates. Automation
should pass credentials with `RVS_TOKEN`; that env var takes precedence over local
profiles, requires no keyring, vault, or D-Bus session, and is never refreshed.

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

The alpha CLI currently targets DevAPI's explicitly unstable `/v0` generation.
`rvs/devapi.py` is the only generation selector: commands pass unversioned
resource paths, including device login, refresh, and revoke. Responses that
report a different `Ravenstash-API-Version` are rejected. A future `/v1beta1`
or `/v1` adoption therefore ships as a reviewed CLI release instead of scattered
path edits; retained CLI releases remain pinned to their declared generation.

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
rvs account use acmeHQ
rvs context current
```

Headless automation must make this selection explicitly; device authentication
does not imply a package customer. For a personal account use
`rvs account use personal`. Before selecting an official private mirror,
initialize its remote cache for the selected account once, for example
`rvs art mirror add pypiorg`, `rvs art mirror add npmjs`, or
`rvs art mirror add maven-central`. A `mirror:<source>` request returns 404 until
that binding exists; it is an authorization boundary, not a transient cache miss.

Readable repository names resolve only within the effective acting account.
Explicit stable repository references (`in_…/r_…`, or bare `r_…` where repository
management commands accept it) may resolve across accounts the authenticated user
is authorized to access. Cross-account resolution prints the owning account;
`--json` emits a `cross_account_resource` info event on stderr with the selected
and owning customer IDs. It does not switch the acting account or grant access.
Credentials, resource authorization, and usage attribution follow the owner.
PAT/workload credentials remain bound to their configured account and grants;
stable references do not broaden their authority or fall back to a human login.
Manual `rvs art auth print-token` keeps ownership diagnostics on stderr so stdout
contains only the requested secret or JSON response.

Selecting a cross-account target saves it in the current account's local context,
without replacing the owning account's separately saved target. Subsequent use
re-resolves the stable reference and repeats the ownership hint. `rvs art current`
shows the target owner ID. Readable names remain account-scoped even after such a
selection. The reserved public catalog scope remains unavailable.

Account and artifact target selections are stored locally; tokens remain in the
selected credential store.

`rvs auth whoami` verifies the current identity against Ravenstash; it does not
infer identity solely from local profile metadata. `rvs context current` combines
that verified user with the effective local profile, acting account, package
target, and the source of each selection.

The former context-prompt shell commands have been removed. If previously installed,
manually remove the line sourcing `~/.rvs/shell.sh` from `.bashrc` or `.zshrc`,
or the corresponding source line in `~/.config/fish/conf.d/rvs-context.fish`,
and restart the shell. Upgrading does not edit your startup files.

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

Publishing requires confirmation of the resolved repository, acting account, and artifacts.
Use `--yes` (`-y`) with `rvs art pypi publish`, `rvs art npm publish`, or
`rvs art maven deploy` to skip confirmation. Native wrappers accept `--rvs-yes`
(for example, `rvs npm --rvs-yes --rvs-target platform/backend publish`).
Unattended publishing must pass the bypass flag. Native builds show their project
or supplied references because the final artifacts may be produced during execution.

The preview groups PyPI files by package/version, shows npm name/version and tarball,
Maven coordinates and filenames, and full Container/Helm OCI references when known.
For example, publishing a single additional wheel shows only that wheel:

```text
Publish to platform/backend (org:YYYY)

PyPI acme-sdk==1.4.0
  acme_sdk-1.4.0-cp312-cp312-win_amd64.whl

Publish this 1 file? [y/N]:
```

This confirms the selected files, not the completeness of a release. PyPI supports
adding new filenames to an existing version later; existing filenames cannot be
overwritten. Uploads are independent, so retry only missing files after partial failure.

Package repository commands are under `rvs art`. This area connects the local
machine and native package managers to a remote Ravenstash package repository.

Repository commands:

```bash
rvs art repo list
rvs art repo list --registry-kind pypi
rvs art repo create my-python-packages --registry-kind pypi --default
rvs art repo create runtime-images --registry-kind container --default
rvs art repo create deployment-charts --registry-kind helm --default
rvs art repo show <repo-name>
rvs art repo rename <repo-name> <new-name>
rvs art repo delete <repo-name>
rvs art repo set-default pypi <repo-name>
rvs art repo defaults
rvs art repo upstream list acme/app pypi
rvs art repo upstream add acme/app pypi --private-repository acme/libraries
rvs art repo upstream add acme/app pypi --remote-cache pypiorg
rvs art repo upstream update acme/app pypi <attachment-id> --min-age-hours 1
rvs art repo upstream reorder acme/app pypi <attachment-id> <attachment-id>
rvs art repo upstream remove acme/app pypi <attachment-id>

rvs art mirror list
rvs art mirror create --registry-kind pypi
rvs art mirror show <cache-id>
rvs art mirror set-age <cache-id> --min-age-hours 24
rvs art mirror delete <cache-id>
```

Select one typed target without reserving namespace names:

```bash
rvs art select acme/backend
rvs art --scope self select acme/backend
# Reserved public catalog scope; currently reports PublicCatalogUnavailable.
rvs art --public select acme/backend
rvs art select mirror:pypiorg
rvs art select custom-mirror:piwheels
rvs art current
rvs art clear

rvs art --target acme/backend --kind pypi install internal-lib
rvs art --target mirror:pypiorg install requests
rvs art --target custom-mirror:piwheels --kind pypi install numpy
```

`rvs art mirror` manages the private install surface backed by each remote cache.
Official and custom mirrors stay visibly distinct:

```bash
rvs art mirror add pypiorg --select
rvs art mirror create-custom piwheels --kind pypi \
  --api-url https://www.piwheels.org/simple/ \
  --publication-control externally-controlled --select
rvs art mirror select pypiorg
rvs art mirror select --custom piwheels
```

A remote cache is a customer-owned read-only binding to a curated or custom
registry. Its private mirror is always available to authorized users with an
independent 24-hour minimum-age default. Connect the remote cache to a repository
with `--remote-cache`; select `mirror:` for direct package-manager use. A private
PyPI, npm, or Maven lane can also attach a same-kind private
lane from the same customer, including another namespace. Private sources expose
only their intrinsic packages; their own upstream plans are never traversed.
Private attachments default to zero/disabled minimum age, while official remote
attachments retain the server recommendation. Container and Helm are private-only.

Repository names use lowercase letters, numbers, and hyphens. Package targets
use `<namespace>/<repo-name>` within the acting account; no realm prefix or `@`
notation is needed. `--scope self` is the default. `--public` and `--scope public`
reserve the future public catalog and currently return `PublicCatalogUnavailable`.
When equal names
are authorized across accounts, select the account explicitly. After resolving
the target, the CLI always builds native package URLs from the immutable
`<namespace_unique_ref>/<repository_unique_ref>` pair.

The acting account and selected target are scoped by local profile and immutable
customer ID. Legacy per-kind repository defaults remain readable as a migration
fallback. An explicit `--target` is one-shot and never changes saved state.

`rvs account use HANDLE` matches customer handles without regard to letter case
and preserves the chosen casing for display. Handles can change; saved contexts
remain keyed by the existing customer ID. `rvs art repo create namespace/repository`
resolves an accessible namespace and creates through its immutable reference; a
bare repository name uses the account's default internal namespace.

Saved defaults store immutable namespace and repository references as identity
and keep names only as display hints. A later namespace or repository rename
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
rvs art package list --repo <repo-name> --registry-kind pypi
rvs art package show requests --repo <repo-name> --registry-kind pypi
rvs art package delete requests --repo <repo-name>
rvs art package delete-version requests 2.32.0 --repo <repo-name>
rvs art package yank requests 2.32.0 --repo <repo-name> --reason "bad build"
```

PyPI helpers:

```bash
rvs art pypi index-url --repo <repo-name>
rvs art pypi upload-url --repo <repo-name>
rvs art pypi install requests --repo <repo-name>
rvs art pypi publish dist/ --repo <repo-name>
rvs art pypi configure --repo <repo-name>
```

The install helper sets Ravenstash as pip's primary `PIP_INDEX_URL`; it does not
add a second index that could silently win dependency resolution.

npm helpers:

```bash
rvs art npm registry-url --repo <repo-name>
rvs art npm npmrc --repo <repo-name>
rvs art npm install lodash --repo <repo-name>
rvs art npm publish . --repo <repo-name>
rvs art npm configure --repo <repo-name>
```

Direct npm publishing uses native `npm pack` before sending the wire payload, so
npm packlists, lifecycle hooks, bundled dependencies, and generated files are
honored. An `npm` executable is required.

Maven helpers:

```bash
rvs art maven repo-url --repo <repo-name>
rvs art maven settings --repo <repo-name>
rvs art maven install com.example:lib:1.0.0 --repo <repo-name>
rvs art maven deploy ./target/lib.jar --group com.example --artifact lib --version 1.0.0 --repo <repo-name>
rvs art maven configure --repo <repo-name>
```

Package-token management is intentionally not part of the alpha CLI surface.

Native package-manager wrappers:

```bash
rvs pip install acme-utils
rvs uv sync
rvs twine upload dist/*
rvs npm install @acme/widgets
rvs mvn test
rvs docker --rvs-target acme/runtime-images pull api:latest
rvs helm --rvs-target acme/deployment-charts show chart oci://oci.rvsta.sh/acme/deployment-charts/charts/api --version 1.2.3
rvs oras --rvs-kind container --rvs-target acme/runtime-images discover oci.rvsta.sh/acme/runtime-images/api:latest
rvs oci-reference --kind container --target acme/runtime-images --oci-path api --reference latest

rvs npm --rvs-target acme/my-node-packages install @acme/widgets
rvs pip --rvs-target acme/my-python-packages install acme-utils
rvs uv --rvs-target acme/my-python-packages --rvs-native-config isolate sync
```

`rvs art ...` is Ravenstash-native: it selects a typed Ravenstash target through
`--target` or the effective local-profile/acting-account context, and the underlying implementation may or may
not use a native package manager. `rvs pip`, `rvs uv`, `rvs twine`, `rvs npm`,
`rvs mvn`, `rvs docker`, `rvs helm`, and `rvs oras` are explicit native-tool passthroughs. The
package-release wrappers require an explicit `--rvs-target` or a selected target
(including retained legacy defaults). A registry URL in native configuration alone
is not a target selection. Without a target, they stop before launching the native
operation; help and version queries do not require a target.

The selected target supplies the default index/registry. Explicit additional
indexes, npm scope registries, and native dependency/lockfile source assignments
remain available. Source inspection emits an advisory warning when local inputs
reference URLs outside the selected target; it does not rewrite or reject them.
Inspection covers common config files, uv/npm lockfiles, and local requirements
includes. It is best effort, not an exhaustive effective-config resolver or a
network sandbox: remote includes, generated configuration, build scripts, and
plugins can introduce further destinations. Downloads outside the selected target
bypass its policy and accounting and require native authentication.

`rvs` never migrates or regenerates lockfiles itself. Use `rvs uv lock` or
`rvs npm install --package-lock-only` to request native lock generation. Native
semantics remain intact: `uv sync` and `npm install` may update their locks; use
`rvs uv sync --locked` or `rvs npm ci` when changes must be rejected.

pip keeps extra indexes and find-links; its index candidates have no priority.
uv keeps named indexes and package-to-index source mappings. npm keeps explicit
scope registry mappings. Maven's generated settings mirror `central`, preserving
other repositories and credentials. Existing mirror patterns are excluded from
Central and the reserved `rvs-private` repository in the temporary settings, with
a warning, so they cannot redirect the selected target. Explicit
`--rvs-native-config isolate` still requests native config isolation and a Maven
wildcard mirror; it is not a network sandbox. `respect` and `override` both set
the selected target as the default while preserving additional sources.

Native wrappers request a fresh four-hour `rvs_slt` token per invocation. Current
clients use static environment/config credentials, so a running command cannot
renew them automatically. Start a new command to obtain a new token; operations
lasting beyond its expiry may require a retry. Source revocation can end access
sooner. The CLI retries transient issuance failures at most twice within a bounded
request budget; authorization failures are terminal.

To generate a token for manual configuration:

```sh
rvs artifacts auth print-token --target mynamespace/myrepo --kind pypi --access read --duration 4h
```

Manual duration accepts 15 minutes to 12 hours. Stdout contains only the secret
unless `--json` is requested. Prefer regular `rvs` commands on a developer laptop.
For CI, provide a scoped `rvs_ust`, `rvs_uot` or `rvs_oat` through `RVS_TOKEN` and
let the CLI exchange it. Direct use of a durable token in a native registry is
controlled by the applicable account policy, discouraged and may be removed.

Only short-lived credentials are injected for the child process. Install/read commands request download-only
capabilities; publish/deploy/push commands request upload authority only when the
native workflow needs it. They do not write tokens to `.npmrc`,
`pip.conf`, `.pypirc`, `settings.xml`, `pyproject.toml`, or `uv.toml`.
The controlling `RVS_TOKEN`, when present, is removed from every launched native
process after the scoped package capability has been exchanged. Temporary netrc,
Maven settings, OCI config, and OCI broker files are removed when the wrapper exits.
Python's temporary netrc preserves existing credentials for other hosts. Netrc is
host-scoped, not path-scoped; another repository on the same host needs explicit
native authentication if it cannot use that entry. The Ravenstash capability
remains authorized for only the selected target. npm credentials use the selected
registry path; Maven credentials use the reserved target server ID. uv read/lock
commands inject no publish credentials and support read-only private mirrors.

The registry protocol supports a broader native-client compatibility matrix than
the passthrough command list. Poetry; Yarn, pnpm, and Bun; Gradle and sbt; and
Podman, nerdctl, Skopeo, and Crane use their own native configuration with an
explicitly generated `rvs_slt` token; there are no corresponding `rvs <tool>` passthroughs yet. A catalog
client association means protocol compatibility, not the existence of an RVS
wrapper.

The OCI wrappers resolve one exact Container or Helm lane, request a scoped
capability, and overlay an ephemeral `docker-credential-rvs` entry on a copy of
the native registry config. Existing credentials for other registries are
preserved; stale Ravenstash auth entries are removed from the copy. The token is
never placed in argv or written to the user's Docker or Helm config. Docker,
Helm, and ORAS all use the same `oci.rvsta.sh` host and the stable
`/<namespace-ref>/<repository-ref>/...` namespace. `rvs oras` requires
`--rvs-kind container` or `--rvs-kind helm` because ORAS supports both lanes.

With a private repository selected, Docker push, pull, and tag accept image names
without the registry address. The equivalent `rvs docker image push`, `image pull`,
and `image tag` forms work too:

```bash
rvs art select acme/runtime-images
docker build -t team/api:1.2 .
rvs docker push team/api:1.2
rvs docker pull team/api:1.2
rvs docker tag local-api:dev team/api:next
```

These commands also accept `--rvs-target acme/runtime-images` instead of a saved
selection. Shorthand resolves against the discovered OCI endpoint and repository
identity; it never falls back to Docker Hub. An omitted tag means `latest`.
Nested paths such as `team/backend/api` are supported, and tag case is preserved.
An explicit registry hostname is never prefixed or redirected. Docker's hostname
rules apply: a first path component containing a dot or colon, `localhost`, or an
uppercase character denotes a registry, so use the full internal reference for
an internal image path such as `team.v2/api`. Use plain `docker pull nginx` for
public images.

Push shorthand confirms the resolved publishing destination, inspects the named
local image, and creates a qualified local tag before pushing. The original tag
is preserved. A destination tag pointing to a different image is rejected, even
with `--rvs-yes`; explicitly replace it with plain
`docker tag <source> <full-destination>` when intended. This also applies after
rebuilding a mutable tag such as `latest`. Qualified tags remain after successful
or failed pushes. Tag shorthand qualifies only the destination, and accepts a
local image ID or a fully qualified image as its source.

Pull shorthand retains the fully qualified image name and prints it to stderr;
it does not create a short local alias. Use that full reference with `docker run`,
or explicitly create an alias with plain `docker tag`. Pulls by
`team/api@sha256:<digest>` and `pull --all-tags team/api` are supported.
`push --all-tags` requires a fully qualified reference; push shorthand does not
infer a destination from an image ID or digest.

Build output tags, Dockerfile `FROM`/`COPY --from` references, and local commands
such as run, inspect, and remove retain native Docker naming. For a build using
private base images, write their full references in the Dockerfile and use
`rvs docker build -t team/api:1.2 .` to supply temporary credentials. Public bases
continue using their own registries and existing Docker credentials. One build
can access only the selected Ravenstash repository through the injected credential.
Buildx output tags and registry cache references likewise require explicit URLs.
Docker global options such as `--context`, `--host`, and `--config` go before the
Docker subcommand. The wrapper preserves the selected context, CLI plugins, and
Buildx configuration while using a temporary registry credential overlay.

### Helm chart shorthand

```bash
rvs art select platform/deployment-charts
rvs helm package ./api
rvs helm push api-1.2.3.tgz
rvs helm push api-1.2.3.tgz team/backend
rvs helm pull team/backend/api --version 1.2.3
rvs helm install my-release team/backend/api --version 1.2.3
rvs helm upgrade my-release team/backend/api --version 1.2.3
rvs helm show values team/backend/api --version 1.2.3
rvs helm template my-release team/backend/api --version 1.2.3
```

An omitted push destination uses the selected repository root. An explicit short
push destination is a directory; Helm appends the chart name and version from
its metadata. Read commands include the chart name and use native `--version`
selection (including ranges), or a `name@sha256:...` digest reference.

Only chart operands are expanded. Release names, values files, and flags retain
native meaning. Full `oci://` and HTTP URLs stay explicit; `--repo` opts into
Helm's supplied repository URL. Local directories require `./`, `../`, or an
absolute path; `.tgz` paths stay local. A bare chart name remains private even
when a local directory has that name. Repository aliases such as `bitnami/nginx`
are private paths inside `rvs helm`; use plain Helm for configured public aliases.
Private misses never fall back publicly.

Keep full repository URLs in `Chart.yaml` dependencies. One invocation still
authorizes one Ravenstash repository. Other commands, including dependency
build/update and package, keep their native arguments. `--registry-config` is
used as the source for the temporary credential overlay, never as a way to bypass
it. Unknown value flags can use `--option=value`; unknown bare flags are rejected
rather than guessing which following operand is a chart.

## Installation

The supported end-user install path is a signed self-contained distribution,
not `pip install`. The CLI embeds Python 3.14; it does not use the system Python.
User config, credentials, and managed runtimes stay in `~/.rvs`.

The first public release targets this platform matrix. A target becomes supported
when its signed release artifact passes clean-system certification.

| Platform | Architectures | Install path |
| --- | --- | --- |
| Linux with glibc 2.28+ | x86-64, ARM64 | APT package or portable archive |
| Linux with musl, including Alpine | x86-64, ARM64 | portable archive |
| macOS 14+ on Apple Silicon; macOS 15+ on Intel | Apple Silicon, Intel | `install.sh` |
| Windows 10/11 on x64; Windows 11 on ARM | x64, ARM64 | `install.ps1` |
| NixOS and Nix on Linux/macOS | x86_64, aarch64 | versioned flake package |
| WSL2 | x86_64, aarch64 | matching Linux path |

Install the current recommended compatibility channel on Linux, WSL, or macOS:

```bash
curl -fsSL https://ravenstash.com/install.sh | bash
```

On Windows PowerShell:

```powershell
irm https://ravenstash.com/install.ps1 | iex
```

During the private alpha, set `RVS_GITHUB_TOKEN` to a read-only token for this
repository before running either command. Public releases do not require it.

Debian, Ubuntu, WSL, and derivatives use the signed APT channel. Other Linux
systems and macOS use a portable archive authenticated by its OpenPGP-signed
checksum inventory. Native artifacts cover Linux glibc and musl, macOS, and
Windows on both x86-64 and ARM64. macOS release executables are signed and
notarized; Windows release executables carry Authenticode signatures. Review the installer source at
<https://ravenstash.com/install.sh> before running it if required by your
environment. Set `RVS_INSTALL_SCOPE=system` for `/opt/rvs` plus
`/usr/local/bin`; the default portable install is rootless and per-user.

See the [platform compatibility policy](docs/linux-compatibility.md) for exact
OS floors, runtime availability, credential storage, and evaluation-only targets.

Nix users install the versioned flake:

```bash
nix profile install github:rvstash/ravenstash-cli-alpha/v0.12.0
```

Direct `.deb` artifacts are also published for early testing:

```bash
sudo apt install ./rvs_<version>_<architecture>.deb
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

Portable installations are updated by rerunning the signed installer. APT remains
the in-CLI update authority; package-manager manifests for Homebrew, WinGet, and
Nix must preserve the same compatibility-channel boundary before publication.

WSL/headless/server note: `RVS_TOKEN` works without extra setup and is the
recommended CI path. Interactive WSL users without Secret Service or `pass` can
use the encrypted Ravenstash vault; its passphrase is requested on creation and
once after the vault agent is lost, locked, or idle for eight hours. Run
`rvs auth storage doctor` before login to see exactly what this session can use.
Vault passphrases require 8 characters; 12+ characters or a short multi-word
passphrase is recommended, and shorter accepted passphrases display a warning.

## Release packaging

Cross-platform package scaffolding lives under `packaging/`. From this folder:

```bash
packaging/scripts/build-release-artifacts.sh
```

The canonical compatibility build runs inside the pinned Ubuntu 20.04 builder:

```bash
packaging/scripts/build-in-ubuntu20.sh
```

That builds the Python 3.14 Linux PyInstaller bundle, Debian package, tarball,
CycloneDX SBOM, and checksum file. Native macOS, Windows, and musl builders run
in the platform and release workflows and feed one attested artifact inventory.
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
├── artifacts/
│   └── registries/
├── ci/
├── client.py
├── config.py
└── output.py
```
