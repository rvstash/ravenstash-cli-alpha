# rvs - Ravenstash Developer CLI

`rvs` is the alpha command line for Ravenstash developer products. Package
repositories are one product area; source repositories, CI, and other tooling
will sit beside it rather than inside it.

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
rvs runtime install python 3.12
rvs runtime install node 22
rvs runtime install java 21
rvs runtime list
rvs runtime which python 3.12
rvs runtime use python 3.12
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
rvs pkg repo list --ecosystem pypi
rvs pkg repo create my-python-packages --ecosystem pypi --default
rvs pkg repo show <repo-name>
rvs pkg repo rename <repo-name> <new-name>
rvs pkg repo delete <repo-name>
rvs pkg repo set-default pypi <repo-name>
rvs pkg repo defaults
rvs pkg repo set-upstream <repo-name> <cache-id> --min-age-days 3
rvs pkg repo clear-upstream <repo-name>

rvs pkg remote-cache list
rvs pkg remote-cache create --ecosystem pypi
rvs pkg remote-cache show <cache-id>
rvs pkg remote-cache set-age <cache-id> --min-age-days 3
rvs pkg remote-cache delete <cache-id>
```

A remote cache & proxy is a customer-owned read-only binding to a curated
public registry. Use it directly with package managers or connect it to a
private repository. Packages are cached on demand and can be delayed with
minimum package age.

Repository references use the package repository name, such as
`my-python-packages`. Repository names use lowercase letters, numbers, and
hyphens. When a name is ambiguous across authorized workspaces, use
`<workspace>/<repo-name>` or pass `--customer-id`. After resolving the target,
the CLI always builds native package URLs from the immutable
`<workspace_unique_ref>/<repository_unique_ref>` pair.

Defaults are profile-scoped under
`[profiles.<name>.registries.<ecosystem>]` in `~/.rvs/config.toml`. Legacy top-level
registry defaults remain readable as a migration fallback.

Package metadata commands:

```bash
rvs pkg package list --repo <repo-name> --ecosystem pypi
rvs pkg package show requests --repo <repo-name> --ecosystem pypi
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

rvs npm --rvs-repo my-node-packages install @acme/widgets
rvs pip --rvs-repo my-python-packages install acme-utils
rvs uv --rvs-repo my-python-packages --rvs-native-config isolate sync
```

`rvs pkg ...` is Ravenstash-native: it selects the Ravenstash repository through
`--repo` or `~/.rvs/config.toml`, and the underlying implementation may or may
not use a native package manager. `rvs pip`, `rvs uv`, `rvs twine`, `rvs npm`,
and `rvs mvn` are explicit native-tool passthroughs: they respect native config
by default, detect Ravenstash registry URLs, and inject only short-lived
credentials for the child process. They do not write tokens to `.npmrc`,
`pip.conf`, `.pypirc`, `settings.xml`, `pyproject.toml`, or `uv.toml`.

## Installation on Ubuntu / WSL

The supported end-user install path is a system package, not `pip install`.
The Linux package contains a self-contained CLI and installs both `/usr/bin/rvs`
and the long-form `/usr/bin/ravenstash` alias; user config, credentials, and
managed runtimes stay in `~/.rvs`.

APT repository install:

```bash
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://downloads.ravenstash.com/rvs/apt/ravenstash-rvs.gpg \
  | sudo tee /etc/apt/keyrings/ravenstash-rvs.gpg >/dev/null
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/ravenstash-rvs.gpg] https://downloads.ravenstash.com/rvs/apt stable main" \
  | sudo tee /etc/apt/sources.list.d/ravenstash-rvs.list
sudo apt update
sudo apt install rvs
```

Direct `.deb` artifacts are also published for early testing:

```bash
sudo apt install ./rvs_<version>_amd64.deb
```

WSL/headless note: `RVS_TOKEN` works without extra setup. Persistent
`rvs auth login` stores access and refresh tokens in the OS keyring, so WSL
needs a usable keyring service before local login credentials can be saved.

## Release packaging

Linux package scaffolding lives under `packaging/`. From this folder:

```bash
packaging/scripts/build-release-artifacts.sh
```

That builds the PyInstaller bundle, Debian package, tarball, and checksum file.
APT repository metadata is generated separately:

```bash
RVS_APT_GPG_KEY_ID=<key-id> packaging/scripts/update-apt-repo.sh
```

## Local Development

Use the package venv directly from this folder:

```bash
cd packages/rvs
source .venv/bin/activate
python -m pip install -e .
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
