# rvs Package Registry Quickstart

This tutorial shows how to use the `rvs` CLI with Ravenstash private package
repositories for PyPI, npm, and Maven. It is written for both humans and LLM
agents, so it includes the operational model, command sequence, and failure
cases that matter when automating workflows.

## Mental Model

`rvs auth login` authenticates one Ravenstash user through a named local CLI
profile. Select the acting personal account or organization separately, then
select a typed private repository or private-mirror target.

The four context layers are intentionally distinct:

- **user** — the authenticated human and audit actor;
- **local profile** — a named CLI configuration and credential slot;
- **acting account** — the personal or organization authorization and metering boundary;
- **package target** — the repository or private mirror used inside that account.

Package commands resolve a repository selector through DevAPI:

- a bare repository name works when it matches exactly one authorized object;
- `<workspace>/<repository-name>` disambiguates mutable names;
- saved defaults contain immutable
  `<workspace_unique_ref>/<repository_unique_ref>` pairs.

When a package command needs a target, `rvs` resolves it in this order:

1. Use the one-shot `--target`, if provided.
2. Use the selected target for the effective `(local profile, acting account)` pair.
3. Read a legacy per-kind private default during migration.
4. For `rvs pkg` read/install helpers, use the account-scoped official default
   (`pypiorg`, `npmjs`, or `maven-central`) when its direct binding is enabled.

The error looks like this:

```text
No pypi package target is selected. Pass --target or run `rvs pkg select`.
```

The same pattern applies to `npm` and `maven`.

## Prerequisites

Install `rvs` and make sure it is on `PATH`:

```bash
rvs --help
```

For install flows, the native package manager must also be available:

```bash
python3 -m pip --version
npm --version
mvn --version
```

`rvs` can manage Python, Node.js, and Java runtimes, but Maven itself is treated
as a system tool.

## Authenticate

Interactive login uses the Ravenstash device authorization flow:

```bash
rvs auth login
```

For a named profile:

```bash
rvs auth login --profile staging
rvs profile use staging
```

Credential behavior:

- Device login stores access and refresh tokens in the selected OS keyring,
  initialized `pass` store, or passphrase-encrypted Ravenstash vault.
- If none is available, the first login runs credential-storage setup before
  browser authorization. Plaintext storage is an explicit discouraged option,
  never an automatic fallback.
- Local profile metadata lives in `~/.rvs/config.toml`.
- `RVS_TOKEN` overrides stored credentials and is the automation path.
- Never commit real tokens or `.env` files containing secrets.

After login, inspect authentication and local-profile state separately:

```bash
rvs auth status
rvs auth whoami
rvs profile current
rvs auth storage doctor
```

Select the acting account and enable the persistent terminal hint:

```bash
rvs account list
rvs account use org:acme
rvs context current
rvs shell setup
rvs pkg select acme/backend
```

For a personal account, use `rvs account use personal` instead. Acting-account
selection is mandatory in headless flows even immediately after device login.
Official private-mirror use requires its remote cache to be initialized once for
the selected account:

```bash
rvs pkg mirror add pypiorg
rvs pkg mirror add npmjs
rvs pkg mirror add maven-central
```

Without that binding, `mirror:pypiorg` (or its npm/Maven equivalent) returns 404
by design. Initialization creates an authenticated private mirror with a 24-hour
minimum-age default; merely knowing the curated slug does not grant access.

The prompt becomes `(staging · org:acme · acme/backend)`. Two named login
profiles may select the same organization while retaining distinct audit actors.

`whoami` verifies and reports only the authenticated user through DevAPI.
`context current` combines that user with the effective local profile, acting
account, package target, and selection provenance.

## Create Or Select Repositories

List repositories owned by the selected personal account or organization:

```bash
rvs pkg repo list
rvs pkg repo list --registry-kind pypi
rvs pkg repo list --registry-kind npm
rvs pkg repo list --registry-kind maven
rvs pkg repo list --registry-kind container
rvs pkg repo list --registry-kind helm
```

Create a repository and make it the default for that registry kind:

```bash
rvs pkg repo create my-python-packages --registry-kind pypi --default
rvs pkg repo create my-node-packages --registry-kind npm --default
rvs pkg repo create my-java-packages --registry-kind maven --default
rvs pkg repo create runtime-images --registry-kind container --default
rvs pkg repo create deployment-charts --registry-kind helm --default
```

Repository names use lowercase letters, numbers, and hyphens.

Or set defaults for existing repositories:

```bash
rvs pkg repo set-default pypi <pypi-repo-name>
rvs pkg repo set-default npm <npm-repo-name>
rvs pkg repo set-default maven <maven-repo-name>
rvs pkg repo set-default container <container-repo-name>
rvs pkg repo set-default helm <helm-repo-name>
```

Check defaults:

```bash
rvs pkg repo defaults
```

You can always bypass defaults with `--repo`:

```bash
rvs pkg pypi install requests --repo <pypi-repo-name>
rvs pkg npm install lodash --repo <npm-repo-name>
rvs pkg maven install com.example:lib:1.0.0 --repo <maven-repo-name>
```

Use `<workspace>/<repo-name>` to disambiguate equal repository names:

```bash
rvs pkg pypi index-url --repo <workspace>/<repo-name>
```

The CLI resolves that selector, saves immutable references for persistent
defaults, and always generates native package URLs in this stable form:

```text
/w_abcdefgh/r_m7nk3p4q/
```

Workspace and repository renames therefore do not break CLI defaults.

## `rvs pkg` vs Native Package-Manager Wrappers

`rvs pkg ...` is the Ravenstash-native package workflow. It selects the
Ravenstash repository from `--repo` or the saved default in `~/.rvs/config.toml`.
The implementation may delegate to a native package manager or use Ravenstash
registry adapters directly; that detail is not part of the user contract.

The top-level native wrappers explicitly run the named package manager:

```bash
rvs pip install private-package
rvs uv sync
rvs twine upload dist/*
rvs npm install @acme/widgets
rvs mvn test
rvs docker --rvs-repo <container-repo-name> pull oci.rvsta.sh/<workspace-name>/<container-repo-name>/api:latest
rvs helm --rvs-repo <helm-repo-name> show chart oci://oci.rvsta.sh/<workspace-name>/<helm-repo-name>/charts/api --version 1.2.3
rvs oras --rvs-kind container --rvs-repo <container-repo-name> discover oci.rvsta.sh/<workspace-name>/<container-repo-name>/api:latest
```

By default, the wrappers respect native config such as `.npmrc`, `pip.conf`,
`.pypirc`, `settings.xml`, `pyproject.toml`, and `uv.toml`. If those files or
the command arguments reference Ravenstash registry URLs, `rvs` injects a
short-lived token only for the subprocess. It does not write tokens to
persistent package-manager config files.

Docker, Helm, and ORAS share Ravenstash's OCI endpoint. Their wrappers select
one exact repository, request a scoped ephemeral credential, and overlay the
`docker-credential-rvs` helper on a temporary copy of the native registry
config. Existing credentials for other hosts are preserved and no Ravenstash
secret is written to the user's config or command line. Use
`rvs oci-reference --kind container|helm` to print a stable customer-facing
reference; the clients' internal `/v2/` requests are intentionally hidden.

Use `--rvs-repo` when the wrapper should override native registry selection for
one invocation:

```bash
rvs npm --rvs-repo <npm-repo-name> install @acme/widgets
rvs npm --rvs-repo <npm-repo-name> publish
rvs pip --rvs-repo <pypi-repo-name> install private-package
rvs uv --rvs-repo <pypi-repo-name> sync
rvs twine --rvs-repo <pypi-repo-name> upload dist/*
rvs mvn --rvs-repo <maven-repo-name> deploy
```

Use `--rvs-native-config isolate` for a cleaner subprocess environment where
the native tool supports disabling persistent config:

```bash
rvs pip --rvs-repo <pypi-repo-name> --rvs-native-config isolate install private-package
rvs uv --rvs-repo <pypi-repo-name> --rvs-native-config isolate sync
```

## PyPI

Print the private install and publish URLs:

```bash
rvs pkg pypi index-url
rvs pkg pypi upload-url
```

Install from the private repository:

```bash
rvs pkg pypi install requests
```

For this command, `rvs` delegates to `pip` and injects:

```text
PIP_INDEX_URL=https://__token__:<token>@<pypi-read-host>/<workspace_unique_ref>/<repository_unique_ref>/simple/
```

That environment variable is scoped to the subprocess. It is not written to a
project file. Ravenstash is the primary index for this invocation, avoiding the
ambiguous cross-index resolution caused by adding a private repository as an
extra index.

Publish wheels or source distributions:

```bash
python3 -m build
rvs pkg pypi publish dist/
```

Current behavior: `rvs pkg pypi publish` does not shell out to `twine`. It
implements the legacy PyPI upload protocol directly and posts to:

```text
https://<pypi-push-host>/<workspace_unique_ref>/<repository_unique_ref>/
```

To print a pip configuration snippet instead of running an install:

```bash
rvs pkg pypi configure
```

## npm

Print the private npm registry URL:

```bash
rvs pkg npm registry-url
```

Install from the private repository:

```bash
rvs pkg npm install lodash
```

For this command, `rvs` delegates to `npm` and runs the equivalent of:

```bash
npm install --registry https://<npm-read-host>/<workspace_unique_ref>/<repository_unique_ref>/ lodash
```

It injects the auth token through npm's environment-backed config key:

```text
NPM_CONFIG_//<npm-read-host>/<workspace_unique_ref>/<repository_unique_ref>/:_authToken=<token>
```

Publish the package in the current directory:

```bash
rvs pkg npm publish .
```

Current behavior: `rvs pkg npm publish` does not shell out to `npm publish`. It
runs native `npm pack`, reads `package.json`, builds the npm publish JSON body,
and PUTs it to:

```text
https://<npm-push-host>/<workspace_unique_ref>/<repository_unique_ref>/<package-name>
```

It writes package metadata with download tarball URLs pointing at the private
download registry:

```text
https://<npm-read-host>/<workspace_unique_ref>/<repository_unique_ref>/<package-name>/-/<tarball>
```

Using `npm pack` honors npm's normal packlist, lifecycle hooks, bundled
dependencies, and generated files. An `npm` executable must be available.

To print an `.npmrc` snippet:

```bash
rvs pkg npm npmrc
rvs pkg npm configure
```

The snippet uses `${RVS_TOKEN}`. Export that variable before using the snippet
with native `npm` commands.

## Maven

Print the private Maven repository URL:

```bash
rvs pkg maven repo-url
```

Fetch an artifact into the local Maven cache:

```bash
rvs pkg maven install com.example:lib:1.0.0
```

For this command, `rvs` writes a temporary `settings.xml` containing:

- server id `rvs-private`
- username `__token__`
- the active token as the password
- repository URL
  `https://<maven-read-host>/<workspace_unique_ref>/<repository_unique_ref>/`

It then runs:

```bash
mvn --settings=<temporary-settings-file> dependency:get -Dartifact=com.example:lib:1.0.0
```

The temporary settings file is removed after the command completes.

Deploy an artifact file:

```bash
rvs pkg maven deploy ./target/lib-1.0.0.jar \
  --group com.example \
  --artifact lib \
  --version 1.0.0
```

Current behavior: `rvs pkg maven deploy` does not shell out to `mvn deploy`. It
uploads the artifact and checksum sidecars with HTTP PUTs under:

```text
https://<maven-push-host>/<workspace_unique_ref>/<repository_unique_ref>/<group-path>/<artifact>/<version>/
```

To print a reusable Maven `settings.xml` snippet:

```bash
rvs pkg maven settings
rvs pkg maven configure
```

The printed snippet uses `${env.RVS_TOKEN}` as the password. Export `RVS_TOKEN`
before using it with native Maven commands.

## Automation Pattern

For CI or headless agents, prefer `RVS_TOKEN` and explicit repository defaults:

```bash
export RVS_TOKEN=<automation-token>
export RVS_PROFILE=ci

rvs pkg repo set-default pypi <pypi-repo-name>
rvs pkg pypi install private-package
```

Do not log tokens. Avoid echoing authenticated PyPI URLs because the token is
embedded in the URL for `pip` compatibility.

## Troubleshooting

No repository selected:

```bash
rvs pkg repo defaults
rvs pkg repo set-default pypi <repo-name>
```

Unknown or ambiguous repository:

```bash
rvs pkg repo list
rvs auth status
rvs auth login
```

Pass `<workspace>/<repo-name>` or the immutable underscore pair shown by
`rvs pkg repo list` when equal names exist in several authorized scopes.

Not authenticated:

```bash
rvs auth login
```

Or for automation:

```bash
export RVS_TOKEN=<automation-token>
```

Native tool missing:

```bash
rvs runtime install python 3.12
rvs runtime install node 22
```

Install Maven through the system package manager or another approved Java build
toolchain path.

## Agent Notes

LLM agents should follow these rules when using `rvs`:

- Do not assume login selects a repository.
- Resolve the target registry kind first: `pypi`, `npm`, or `maven`.
- Prefer `--repo <repo-name>` for one-off commands.
- Use `rvs pkg repo set-default <registry-kind> <repo-name>` only when changing persistent
  local CLI state is intended.
- Treat customer, workspace, and repository internal IDs as different from
  their immutable generated references.
- Private registry URLs always use
  `/<workspace_unique_ref>/<repository_unique_ref>`; never construct them
  from a customer identifier.
- The CLI control plane is DevAPI. Do not configure or call Central directly.
- Use `RVS_TOKEN` for CI/headless flows.
- Never write real tokens into committed files.
- Remember that install flows delegate to native tools. Publish flows use `rvs`
  registry adapters; npm publishing also invokes native `npm pack` first.
