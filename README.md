# rvn — Universal Package Manager CLI for Ravenstash

`rvn` is a unified command-line interface for publishing and consuming packages
across all Ravenstash-hosted registries: **PyPI**, **npm**, and **Maven**.

Instead of configuring twine, `.npmrc`, and Maven `settings.xml` separately, `rvn`
manages credentials in one place and delegates to native toolchains (pip, uv, npm,
mvn) with the right flags injected — or publishes directly using native registry
protocols without requiring external tools.

---

## Concept

```
rvn <kind> <verb> [args]
```

| Command | What it does |
|---|---|
| `rvn pypi publish dist/` | Upload all wheels/sdists in `dist/` to your private PyPI repo |
| `rvn pypi install requests` | Install from private repo (injects `--extra-index-url`) |
| `rvn npm publish` | Publish the current npm package to your private npm repo |
| `rvn npm install lodash` | Install from private npm repo (injects `--registry`) |
| `rvn mvn deploy mylib.jar` | Upload a JAR + POM to your private Maven repo |
| `rvn mvn install com.example:lib:1.0` | Fetch artifact (injects Maven settings) |
| `rvn repos list` | List your repositories |
| `rvn repos create my-libs pypi` | Create a new repository |
| `rvn packages list my-pypi` | List packages in a repository |
| `rvn tokens create my-pypi --write` | Create a scoped API token |
| `rvn auth login` | Authenticate with browser/device approval |
| `rvn auth status` | Print the current profile authentication state |
| `rvn auth list` | List profiles and per-kind registry defaults |
| `rvn auth switch` | Select the active profile |
| `rvn auth logout` | Remove the current profile credential |
| `rvn auth delete` | Delete a profile and its stored credential |

---

## Auth, Profiles, And Configuration

Interactive login uses Ravenstash device authorization:

```bash
rvn auth login
rvn auth login --profile staging --api-url https://api.staging-hxa159.ravenstash.com
rvn auth login --duration 8h
```

The CLI creates a device session through DevAPI, prints a human code such as
`ABCD-1234`, and asks the user to open the verification page. The browser page is
`/login/device`; the code is entered there, not embedded in the URL. While the
browser flow completes, the CLI polls `POST /v0/auth/device/token`. `--duration`
preselects the refresh duration on the approval screen; accepted values include
`8h`, `3days`, `1month`, and `1year`. If no duration is provided, the browser
approval defaults to 4 hours. Durations must be between 1 hour and 365 days.
Device login and refresh requests send `User-Agent: rvn/<version>` plus OS
platform metadata for the webapp/backoffice device-session lists.

Successful login stores the short-lived CLI JWT and a profile-scoped device
refresh token in the OS keyring, with profile metadata in `~/.rvn/config.toml`.
If the profile already has an active expiring login, `rvn auth login` replaces
it and best-effort revokes the previous device refresh token after the new login
succeeds.
When the expiring access token expires, `rvn` refreshes automatically through
DevAPI, persists the rotated token pair, and retries the failed request once.
`rvn` does not store PAT/M2M tokens. Automation should pass a customer-scoped
token through `RVN_TOKEN`; that env var always takes precedence over local
keyring/config state and is never refreshed.

Profile commands:

```bash
rvn auth status
rvn auth list
rvn auth switch
rvn auth switch --profile work
rvn auth logout
rvn auth logout --profile work
rvn auth logout --all
rvn auth delete
rvn auth delete --profile work
rvn auth delete --all
```

Default DevAPI URLs:

| Profile | URL |
|---|---|
| `default` | `https://api.ravenstash.com` |
| `staging` | `https://api.staging-hxa159.ravenstash.com` |
| `dev` | `http://localhost:6002` |

Configuration lives at `~/.rvn/config.toml`:

```toml
default_profile = "default"

[profiles.default]
api_url = "https://api.ravenstash.com"
customer_id = "cus_..."
credential_type = "expiring"
expires_at = "2026-06-18T16:00:00+00:00"

[profiles.dev]
api_url = "http://localhost:6002"

# Optional per-kind default repository slug
[registries.pypi]
default_repo = "my-pypi"

[registries.npm]
default_repo = "my-npm"

[registries.maven]
default_repo = "my-maven"
```

Set per-kind default repositories with:

```bash
rvn auth add-registry --kind pypi --repo my-pypi
rvn auth add-registry --kind npm --repo my-npm
rvn auth add-registry --kind maven --repo my-maven
```

Switch profiles with `--profile dev`, `RVN_PROFILE=dev`, or `rvn auth switch`.

---

## How publish works

### PyPI
Implements the [PyPI upload API](https://warehouse.pypa.io/api-reference/legacy.html)
directly (no twine dependency). Reads wheel/sdist metadata, computes SHA-256, posts
multipart form data with HTTP Basic auth (`__token__:{token}`).

### npm
Implements the npm publish wire format: reads `package.json`, creates a `.tgz`
tarball, builds the version manifest JSON, and PUTs it to the registry endpoint.
Alternatively delegates to `npm publish --registry <url>` with auth injected.

### Maven
Implements direct HTTP PUT uploads for JAR, POM, and checksum files.
For complex multi-artifact projects, delegates to `mvn deploy:deploy-file`
with a generated temporary `settings.xml`.

## How install works

`rvn` delegates install operations to native toolchains, injecting private registry
coordinates and auth transparently:

| Kind | Strategy |
|---|---|
| PyPI | Runs `pip install` or `uv pip install` with `--extra-index-url` |
| npm | Runs `npm install` with `--registry` and `_authToken` env var |
| Maven | Runs `mvn dependency:get` with generated `settings.xml` |

---

## Architecture

```
rvn/
├── cli.py              # Root typer app, subcommand registration
├── config.py           # Config file r/w, profile resolution
├── auth.py             # Credential lookup (RVN_TOKEN + keyring)
├── client.py           # httpx-based Ravenstash API client
├── output.py           # Rich console helpers (tables, progress, errors)
├── registries/
│   ├── base.py         # AbstractRegistry protocol + shared types
│   ├── pypi.py         # PyPI multipart publish, pip/uv install delegation
│   ├── npm.py          # npm JSON publish, npm install delegation
│   └── maven.py        # Maven PUT publish, mvn install delegation
└── commands/
    ├── auth.py         # `rvn auth` profile and credential commands
    ├── login.py        # Shared device-authorization implementation
    ├── config.py       # Low-level config helpers
    ├── repos.py        # `rvn repos` subcommands
    ├── packages.py     # `rvn packages` subcommands
    ├── tokens.py       # `rvn tokens` subcommands
    ├── pypi.py         # `rvn pypi` subcommands
    ├── npm.py          # `rvn npm` subcommands
    └── maven.py        # `rvn mvn` subcommands
```

---

## Installation (local dev)

```bash
cd packages/rvn
uv venv && uv pip install -e .
```

Or from the workspace root (once published to the private PyPI registry):

```bash
pip install rvn --extra-index-url https://pypi.ravenstash.com/r/tools/simple/
```
