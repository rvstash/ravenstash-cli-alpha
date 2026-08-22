# rvs - Ravenstash Developer CLI

`rvs` is the alpha command line for Ravenstash developer products. Package
repositories are one product area; source repositories, CI, and other tooling
will sit beside it rather than inside it.

This work-in-progress alpha is developed privately in
`rvstash/ravenstash-cli-alpha`. The first public beta will start a clean public
history in `rvstash/ravenstash-cli`. The CLI is licensed under the
[MIT License](LICENSE).

## Command Surface

```text
rvs auth       Authenticate and manage local profiles
rvs runtime    Install and select local Python, Node, and Java runtimes
rvs pkg        Manage Ravenstash package repositories and package workflows
rvs packages   Alias for rvs pkg
rvs pip        Run pip with ephemeral Ravenstash auth injection
rvs uv         Run uv with ephemeral Ravenstash auth injection
rvs twine      Run twine with ephemeral Ravenstash auth injection
rvs npm        Run npm with ephemeral Ravenstash auth injection
rvs mvn        Run Maven with ephemeral Ravenstash auth injection
rvs repo       Placeholder for future Ravenstash source repositories
rvs ci         Placeholder for future Ravenstash CI
rvs update     Check or apply signed APT updates
```

`rvs repo` and `rvs ci` are intentionally registered now, but their commands only
print "not implemented" until those products exist.

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
in the OS keyring. Profile metadata lives in `~/.rvs/config.toml`. Automation
should pass credentials with `RVS_TOKEN`; that env var takes precedence over
local profiles and is never refreshed.

Device login discovers and stores the package transfer endpoints returned by
DevAPI. Every control-plane operation goes through DevAPI; `rvs` never calls
Central directly. For non-production automation that does not perform device
login, declare the DevAPI and transfer endpoints through the shell environment
or a gitignored local `.rvs.env` file:

```bash
# packages/rvs/.rvs.env, ~/.rvs/profiles.env, or a file pointed to by RVS_ENV_FILE
RVS_PROFILE_STAGING_API_URL=https://<staging-devapi-host>
RVS_PROFILE_STAGING_PKG_DOWNLOAD_URL=https://<staging-download-host>
RVS_PROFILE_STAGING_PKG_UPLOAD_URL=https://<staging-upload-host>
RVS_PROFILE_DEV_API_URL=http://<local-devapi-host>
RVS_PROFILE_DEV_PKG_DOWNLOAD_URL=http://<local-download-host>
RVS_PROFILE_DEV_PKG_UPLOAD_URL=http://<local-upload-host>
```

Process environment variables override env-file values. `RVS_ENV_FILE` can point
to a specific env file when you do not want to place `.rvs.env` in the current
workspace.

Profile commands:

```bash
rvs auth status
rvs auth whoami
rvs auth logout
rvs auth logout --all
rvs auth profile list
rvs auth profile switch work
rvs auth profile delete work
rvs auth profile delete --all
rvs auth profile rename old-name new-name
```

`rvs auth whoami` verifies the current identity against Ravenstash; it does not
infer identity solely from local profile metadata.

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

Package repository commands are under `rvs pkg`; `rvs packages` is the same
command group. This area connects the local machine and native package managers
to a remote Ravenstash package repository.

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
rvs pkg repo set-upstream <repo-name> <cache-id> --min-age-days 3
rvs pkg repo clear-upstream <repo-name>

rvs pkg remote-cache list
rvs pkg remote-cache create --registry-kind pypi
rvs pkg remote-cache show <cache-id>
rvs pkg remote-cache set-age <cache-id> --min-age-days 3
rvs pkg remote-cache delete <cache-id>
```

A remote cache & proxy is a customer-owned read-only binding to a curated
public registry. Use it directly with package managers or connect it to a
private repository. Packages are cached on demand and can be delayed with
minimum package age. Remote caches and upstream attachments are currently
available only for PyPI, npm, and Maven; Container and Helm are private-only.

Repository references use the package repository name, such as
`my-python-packages`. Repository names use lowercase letters, numbers, and
hyphens. When a name is ambiguous across authorized workspaces, use
`<workspace>/<repo-name>` or pass `--customer-id`. After resolving the target,
the CLI always builds native package URLs from the immutable
`<workspace_unique_ref>/<repository_unique_ref>` pair.

Defaults are profile-scoped under
`[profiles.<name>.registries.<registry-kind>]` in `~/.rvs/config.toml`. Legacy top-level
registry defaults remain readable as a migration fallback.

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
rvs docker --rvs-repo runtime-images pull oci.rvsta.sh/x/w_abcdefgh/r_23456789/api:latest
rvs helm --rvs-repo deployment-charts show chart oci://oci.rvsta.sh/x/w_abcdefgh/r_3456789a/charts/api --version 1.2.3
rvs oras --rvs-kind container --rvs-repo runtime-images discover oci.rvsta.sh/x/w_abcdefgh/r_23456789/api:latest
rvs oci-reference --kind container --repo runtime-images --oci-path api --reference latest

rvs npm --rvs-repo my-node-packages install @acme/widgets
rvs pip --rvs-repo my-python-packages install acme-utils
rvs uv --rvs-repo my-python-packages --rvs-native-config isolate sync
```

`rvs pkg ...` is Ravenstash-native: it selects the Ravenstash repository through
`--repo` or `~/.rvs/config.toml`, and the underlying implementation may or may
not use a native package manager. `rvs pip`, `rvs uv`, `rvs twine`, `rvs npm`,
`rvs mvn`, `rvs docker`, `rvs helm`, and `rvs oras` are explicit native-tool passthroughs. The
package-release wrappers respect native config
by default, detect Ravenstash registry URLs, and inject only short-lived
credentials for the child process. They do not write tokens to `.npmrc`,
`pip.conf`, `.pypirc`, `settings.xml`, `pyproject.toml`, or `uv.toml`.

The OCI wrappers resolve one exact Container or Helm lane, request a scoped
capability, and overlay an ephemeral `docker-credential-rvs` entry on a copy of
the native registry config. Existing credentials for other registries are
preserved; stale Ravenstash auth entries are removed from the copy. The token is
never placed in argv or written to the user's Docker or Helm config. Docker,
Helm, and ORAS all use the same `oci.rvsta.sh` host and the stable
`/x/<workspace-ref>/<repository-ref>/...` namespace. `rvs oras` requires
`--rvs-kind container` or `--rvs-kind helm` because ORAS supports both lanes.

## Installation on Ubuntu / WSL

The supported end-user install path is a system package, not `pip install`.
The Linux package contains a self-contained CLI and installs both `/usr/bin/rvs`
and the long-form `/usr/bin/ravenstash` alias; user config, credentials, and
managed runtimes stay in `~/.rvs`.

Install the current recommended Linux compatibility channel:

```bash
curl --proto '=https' --proto-redir '=https' --tlsv1.2 \
  -fsSL https://ravenstash.com/install.sh | bash
```

The installer supports Ubuntu 20.04+ and Debian 11+ on Linux `amd64`. The
package embeds Python 3.14 and does not depend on the system Python. It verifies
the published APT signing-key fingerprint before configuring
`releases.ravenstash.com` and running `apt install rvs`. Review the installer
source at <https://ravenstash.com/install.sh> before running it if required by
your environment.

Direct `.deb` artifacts are also published for early testing:

```bash
sudo apt install ./rvs_<version>_amd64.deb
```

APT remains the update authority:

```bash
rvs update                 # check compatible updates in the current channel
rvs update --apply         # refresh APT metadata and install a compatible update
rvs upgrade --to 0.4       # explicitly accept a newer compatibility channel
sudo apt upgrade           # updates only within the configured channel
```

Before `1.0`, each `v0.Y` APT suite is a compatibility boundary: `0.Y.Z`
patches may update normally, while moving to another minor channel is explicit.
Starting with `1.0`, the major version is the boundary (`v1`, `v2`, and so on).
The CLI authenticates the signed channel manifest before offering or applying a
channel change. It never downloads over and replaces its own executable.

WSL/headless note: `RVS_TOKEN` works without extra setup. Persistent
`rvs auth login` stores access and refresh tokens in the OS keyring, so WSL
needs a usable keyring service before local login credentials can be saved.

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
