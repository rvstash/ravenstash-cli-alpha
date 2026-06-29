# rvn Package Registry Quickstart

This tutorial shows how to use the `rvn` CLI with Ravenstash private package
repositories for PyPI, npm, and Maven. It is written for both humans and LLM
agents, so it includes the operational model, command sequence, and failure
cases that matter when automating workflows.

## Mental Model

`rvn auth login` authenticates a profile. It stores the active customer metadata
and short-lived credentials, but it does not select a package repository.

Package commands need the active customer and a package repository name:

- customer public ID: known after login for the active profile.
- repository name: selected per registry kind, either with `--repo` or a saved
  default.

When a package command needs a repository, `rvn` resolves it in this order:

1. Use `--repo`, if provided.
2. Use `[registries.<kind>].default_repo` from `~/.rvn/config.toml`.
3. Exit with a clear error if neither exists.

The error looks like this:

```text
No pypi package repository selected. Pass --repo or run `rvn pkg repo set-default pypi <repo-name>`.
```

The same pattern applies to `npm` and `maven`.

## Prerequisites

Install `rvn` and make sure it is on `PATH`:

```bash
rvn --help
```

For install flows, the native package manager must also be available:

```bash
python3 -m pip --version
npm --version
mvn --version
```

`rvn` can manage Python, Node.js, and Java runtimes, but Maven itself is treated
as a system tool.

## Authenticate

Interactive login uses the Ravenstash device authorization flow:

```bash
rvn auth login
```

For a named profile:

```bash
rvn auth login --profile staging
rvn auth profile switch staging
```

For local or staging environments, declare the API URL outside git:

```bash
export RVN_PROFILE_STAGING_API_URL=https://<staging-devapi-host>
rvn auth login --profile staging
```

Credential behavior:

- Device login stores access and refresh tokens in the OS keyring.
- Profile metadata lives in `~/.rvn/config.toml`.
- `RVN_TOKEN` overrides stored credentials and is the automation path.
- Never commit real tokens or `.env` files containing secrets.

After login, inspect the active profile:

```bash
rvn auth status
rvn auth whoami
```

## Create Or Select Repositories

List repositories visible to the active customer:

```bash
rvn pkg repo list
rvn pkg repo list --kind pypi
rvn pkg repo list --kind npm
rvn pkg repo list --kind maven
```

Create a repository and make it the default for that registry kind:

```bash
rvn pkg repo create my-python-packages --kind pypi --default
rvn pkg repo create my-node-packages --kind npm --default
rvn pkg repo create my-java-packages --kind maven --default
```

Repository names use lowercase letters, numbers, and hyphens.

Or set defaults for existing repositories:

```bash
rvn pkg repo set-default pypi <pypi-repo-name>
rvn pkg repo set-default npm <npm-repo-name>
rvn pkg repo set-default maven <maven-repo-name>
```

Check defaults:

```bash
rvn pkg repo defaults
```

You can always bypass defaults with `--repo`:

```bash
rvn pkg pypi install requests --repo <pypi-repo-name>
rvn pkg npm install lodash --repo <npm-repo-name>
rvn pkg maven install com.example:lib:1.0.0 --repo <maven-repo-name>
```

Use `<customer-public-id>/<repo-name>` only when you must override the customer
segment encoded in the route:

```bash
rvn pkg pypi index-url --repo <customer-public-id>/<repo-name>
```

Most users should pass just `<repo-name>` because the customer public ID is
already known from the active auth profile.

## `rvn pkg` vs Native Package-Manager Wrappers

`rvn pkg ...` is the Ravenstash-native package workflow. It selects the
Ravenstash repository from `--repo` or the saved default in `~/.rvn/config.toml`.
The implementation may delegate to a native package manager or use Ravenstash
registry adapters directly; that detail is not part of the user contract.

The top-level native wrappers explicitly run the named package manager:

```bash
rvn pip install private-package
rvn uv sync
rvn twine upload dist/*
rvn npm install @acme/widgets
rvn mvn test
```

By default, the wrappers respect native config such as `.npmrc`, `pip.conf`,
`.pypirc`, `settings.xml`, `pyproject.toml`, and `uv.toml`. If those files or
the command arguments reference Ravenstash registry URLs, `rvn` injects a
short-lived token only for the subprocess. It does not write tokens to
persistent package-manager config files.

Use `--rvn-repo` when the wrapper should override native registry selection for
one invocation:

```bash
rvn npm --rvn-repo <npm-repo-name> install @acme/widgets
rvn npm --rvn-repo <npm-repo-name> publish
rvn pip --rvn-repo <pypi-repo-name> install private-package
rvn uv --rvn-repo <pypi-repo-name> sync
rvn twine --rvn-repo <pypi-repo-name> upload dist/*
rvn mvn --rvn-repo <maven-repo-name> deploy
```

Use `--rvn-native-config isolate` for a cleaner subprocess environment where
the native tool supports disabling persistent config:

```bash
rvn pip --rvn-repo <pypi-repo-name> --rvn-native-config isolate install private-package
rvn uv --rvn-repo <pypi-repo-name> --rvn-native-config isolate sync
```

## PyPI

Print the private install and publish URLs:

```bash
rvn pkg pypi index-url
rvn pkg pypi upload-url
```

Install from the private repository:

```bash
rvn pkg pypi install requests
```

For this command, `rvn` delegates to `pip` and injects:

```text
PIP_EXTRA_INDEX_URL=https://__token__:<token>@<api-host>/n/pypi/x/<customer-public-id>/<repo-name>/simple/
```

That environment variable is scoped to the subprocess. It is not written to a
project file.

Publish wheels or source distributions:

```bash
python3 -m build
rvn pkg pypi publish dist/
```

Current behavior: `rvn pkg pypi publish` does not shell out to `twine`. It
implements the legacy PyPI upload protocol directly and posts to:

```text
<api-url>/n/pypi/x/<customer-public-id>/<repo-name>/
```

To print a pip configuration snippet instead of running an install:

```bash
rvn pkg pypi configure
```

## npm

Print the private npm registry URL:

```bash
rvn pkg npm registry-url
```

Install from the private repository:

```bash
rvn pkg npm install lodash
```

For this command, `rvn` delegates to `npm` and runs the equivalent of:

```bash
npm install --registry <api-url>/n/npm/x/<customer-public-id>/<repo-name>/ lodash
```

It injects the auth token through npm's environment-backed config key:

```text
NPM_CONFIG_//<api-host>/n/npm/x/<customer-public-id>/<repo-name>/:_authToken=<token>
```

Publish the package in the current directory:

```bash
rvn pkg npm publish .
```

Current behavior: `rvn pkg npm publish` does not shell out to `npm publish`. It
reads `package.json`, creates a package tarball, builds the npm publish JSON
body, and PUTs it to:

```text
<api-url>/n/npm/x/<customer-public-id>/<repo-name>/<package-name>
```

It writes package metadata with download tarball URLs pointing at the private
download registry:

```text
<api-url>/n/npm/x/<customer-public-id>/<repo-name>/<package-name>/-/<tarball>
```

To print an `.npmrc` snippet:

```bash
rvn pkg npm npmrc
rvn pkg npm configure
```

The snippet uses `${RVN_TOKEN}`. Export that variable before using the snippet
with native `npm` commands.

## Maven

Print the private Maven repository URL:

```bash
rvn pkg maven repo-url
```

Fetch an artifact into the local Maven cache:

```bash
rvn pkg maven install com.example:lib:1.0.0
```

For this command, `rvn` writes a temporary `settings.xml` containing:

- server id `rvn-private`
- username `__token__`
- the active token as the password
- repository URL `<api-url>/n/maven/x/<customer-public-id>/<repo-name>/`

It then runs:

```bash
mvn --settings=<temporary-settings-file> dependency:get -Dartifact=com.example:lib:1.0.0
```

The temporary settings file is removed after the command completes.

Deploy an artifact file:

```bash
rvn pkg maven deploy ./target/lib-1.0.0.jar \
  --group com.example \
  --artifact lib \
  --version 1.0.0
```

Current behavior: `rvn pkg maven deploy` does not shell out to `mvn deploy`. It
uploads the artifact and checksum sidecars with HTTP PUTs under:

```text
<api-url>/n/maven/x/<customer-public-id>/<repo-name>/<group-path>/<artifact>/<version>/
```

To print a reusable Maven `settings.xml` snippet:

```bash
rvn pkg maven settings
rvn pkg maven configure
```

The printed snippet uses `${env.RVN_TOKEN}` as the password. Export `RVN_TOKEN`
before using it with native Maven commands.

## Automation Pattern

For CI or headless agents, prefer `RVN_TOKEN` and explicit repository defaults:

```bash
export RVN_TOKEN=<automation-token>
export RVN_PROFILE=ci

rvn pkg repo set-default pypi <pypi-repo-name>
rvn pkg pypi install private-package
```

If no profile metadata exists for the chosen profile, provide the API URL and
customer public ID through environment/configuration:

```bash
export RVN_PROFILE_CI_API_URL=https://api.ravenstash.com
export RVN_CUSTOMER_PID=<customer-public-id>
export RVN_TOKEN=<automation-token>

rvn pkg pypi install private-package --repo <pypi-repo-name>
```

Do not log tokens. Avoid echoing authenticated PyPI URLs because the token is
embedded in the URL for `pip` compatibility.

## Troubleshooting

No repository selected:

```bash
rvn pkg repo defaults
rvn pkg repo set-default pypi <repo-name>
```

Unknown or missing customer public ID:

```bash
rvn auth status
rvn auth login
```

For automation, set:

```bash
export RVN_CUSTOMER_PID=<customer-public-id>
```

Not authenticated:

```bash
rvn auth login
```

Or for automation:

```bash
export RVN_TOKEN=<automation-token>
```

Native tool missing:

```bash
rvn runtime install python 3.12
rvn runtime install node 22
```

Install Maven through the system package manager or another approved Java build
toolchain path.

## Agent Notes

LLM agents should follow these rules when using `rvn`:

- Do not assume login selects a repository.
- Resolve the target registry kind first: `pypi`, `npm`, or `maven`.
- Prefer `--repo <repo-name>` for one-off commands.
- Use `rvn pkg repo set-default <kind> <repo-name>` only when changing persistent
  local CLI state is intended.
- Treat `customer_id` and `customer_public_id` as different values. Registry
  URLs use `customer_public_id`.
- Use `RVN_TOKEN` for CI/headless flows.
- Never write real tokens into committed files.
- Remember that install flows delegate to native tools, while publish flows use
  `rvn` registry adapters directly in the current implementation.
