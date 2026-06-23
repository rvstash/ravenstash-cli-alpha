# rvn - Ravenstash Developer CLI

`rvn` is the alpha command line for Ravenstash developer products. Package
repositories are one product area; source repositories, CI, and other tooling
will sit beside it rather than inside it.

## Command Surface

```text
rvn auth       Authenticate and manage local profiles
rvn runtime    Install and select local Python, Node, and Java runtimes
rvn pkg        Manage Ravenstash package repositories and package workflows
rvn packages   Alias for rvn pkg
rvn repo       Placeholder for future Ravenstash source repositories
rvn ci         Placeholder for future Ravenstash CI
```

`rvn repo` and `rvn ci` are intentionally registered now, but their commands only
print "not implemented" until those products exist.

## Auth

Interactive login uses Ravenstash device authorization:

```bash
rvn auth login
rvn auth login --profile staging
rvn auth login --duration 8h
```

The CLI stores the short-lived CLI access token and profile-scoped refresh token
in the OS keyring. Profile metadata lives in `~/.rvn/config.toml`. Automation
should pass credentials with `RVN_TOKEN`; that env var takes precedence over
local profiles and is never refreshed.

Non-production API endpoints are not tracked in git. Declare them through the
shell environment or a gitignored local `.rvn.env` file:

```bash
# packages/rvn/.rvn.env, ~/.rvn/profiles.env, or a file pointed to by RVN_ENV_FILE
RVN_PROFILE_STAGING_API_URL=https://<staging-devapi-host>
RVN_PROFILE_DEV_API_URL=http://<local-devapi-host>
```

Process environment variables override env-file values. `RVN_ENV_FILE` can point
to a specific env file when you do not want to place `.rvn.env` in the current
workspace.

Profile commands:

```bash
rvn auth status
rvn auth whoami
rvn auth logout
rvn auth logout --all
rvn auth profile list
rvn auth profile switch work
rvn auth profile delete work
rvn auth profile delete --all
rvn auth profile rename old-name new-name
```

## Runtime

Runtime management is limited to local Python, Node, and Java installs:

```bash
rvn runtime install python 3.12
rvn runtime install node 22
rvn runtime install java 21
rvn runtime list
rvn runtime which python 3.12
rvn runtime use python 3.12
rvn runtime env
rvn runtime setup-shell
rvn runtime doctor
```

`rvn runtime use` writes a local version file such as `.python-version`,
`.node-version`, or `.java-version`.

## Package Repositories

Package repository commands are under `rvn pkg`; `rvn packages` is the same
command group. This area connects the local machine and native package managers
to a remote Ravenstash package repository.

Repository commands:

```bash
rvn pkg repo list
rvn pkg repo list --kind pypi
rvn pkg repo create my-python-packages --kind pypi --default
rvn pkg repo show <repository-id>
rvn pkg repo delete <repository-id>
rvn pkg repo set-default pypi <repository-id>
rvn pkg repo defaults
```

Package metadata commands:

```bash
rvn pkg package list --repo <repository-id>
rvn pkg package show requests --repo <repository-id>
rvn pkg package delete requests --repo <repository-id>
rvn pkg package delete-version requests 2.32.0 --repo <repository-id>
rvn pkg package yank requests 2.32.0 --repo <repository-id> --reason "bad build"
```

PyPI helpers:

```bash
rvn pkg pypi index-url --repo <repository-id>
rvn pkg pypi upload-url --repo <repository-id>
rvn pkg pypi install requests --repo <repository-id>
rvn pkg pypi publish dist/ --repo <repository-id>
rvn pkg pypi configure --repo <repository-id>
```

npm helpers:

```bash
rvn pkg npm registry-url --repo <repository-id>
rvn pkg npm npmrc --repo <repository-id>
rvn pkg npm install lodash --repo <repository-id>
rvn pkg npm publish . --repo <repository-id>
rvn pkg npm configure --repo <repository-id>
```

Maven helpers:

```bash
rvn pkg maven repo-url --repo <repository-id>
rvn pkg maven settings --repo <repository-id>
rvn pkg maven install com.example:lib:1.0.0 --repo <repository-id>
rvn pkg maven deploy ./target/lib.jar --group com.example --artifact lib --version 1.0.0 --repo <repository-id>
rvn pkg maven configure --repo <repository-id>
```

Package-token management is intentionally not part of the alpha CLI surface.

## Installation on Ubuntu / WSL

The supported end-user install path is a system package, not `pip install`.
The Linux package contains a self-contained `rvn` executable and installs it at
`/usr/bin/rvn`; user config, credentials, and managed runtimes stay in `~/.rvn`.

APT repository install:

```bash
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://downloads.ravenstash.com/rvn/apt/ravenstash-rvn.gpg \
  | sudo tee /etc/apt/keyrings/ravenstash-rvn.gpg >/dev/null
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/ravenstash-rvn.gpg] https://downloads.ravenstash.com/rvn/apt stable main" \
  | sudo tee /etc/apt/sources.list.d/ravenstash-rvn.list
sudo apt update
sudo apt install rvn
```

Direct `.deb` artifacts are also published for early testing:

```bash
sudo apt install ./rvn_<version>_amd64.deb
```

WSL/headless note: `RVN_TOKEN` works without extra setup. Persistent
`rvn auth login` stores access and refresh tokens in the OS keyring, so WSL
needs a usable keyring service before local login credentials can be saved.

## Release packaging

Linux package scaffolding lives under `packaging/`. From this folder:

```bash
packaging/scripts/build-release-artifacts.sh
```

That builds the PyInstaller bundle, Debian package, tarball, and checksum file.
APT repository metadata is generated separately:

```bash
RVN_APT_GPG_KEY_ID=<key-id> packaging/scripts/update-apt-repo.sh
```

## Local Development

Use the package venv directly from this folder:

```bash
cd packages/rvn
source .venv/bin/activate
python -m pip install -e .
rvn --help
```

Run checks from `packages/rvn/`:

```bash
.venv/bin/pytest
.venv/bin/ruff check rvn tests
```

## Layout

```text
rvn/
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
