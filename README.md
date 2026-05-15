# rvn — Universal Package Manager CLI for RavenStash

`rvn` is a unified command-line interface for publishing and consuming packages
across all RavenStash-hosted registries: **PyPI**, **npm**, and **Maven**.

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
| `rvn login` | Authenticate and store credentials |
| `rvn config show` | Print current active profile |

---

## Configuration

Configuration lives at `~/.rvn/config.toml`:

```toml
default_profile = "default"

[profiles.default]
api_url = "https://api.ravenstash.com"
token   = "rvn_tok_..."

[profiles.dev]
api_url = "http://localhost:6000"
token   = "rvn_tok_dev_..."

# Optional per-kind default repository slug
[registries.pypi]
default_repo = "my-pypi"

[registries.npm]
default_repo = "my-npm"

[registries.maven]
default_repo = "my-maven"
```

Switch profiles with `--profile dev` or the `RVN_PROFILE` env var.

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
├── auth.py             # Credential storage (keyring + config fallback)
├── client.py           # httpx-based RavenStash API client
├── output.py           # Rich console helpers (tables, progress, errors)
├── registries/
│   ├── base.py         # AbstractRegistry protocol + shared types
│   ├── pypi.py         # PyPI multipart publish, pip/uv install delegation
│   ├── npm.py          # npm JSON publish, npm install delegation
│   └── maven.py        # Maven PUT publish, mvn install delegation
└── commands/
    ├── config.py       # `rvn config` subcommands
    ├── login.py        # `rvn login`
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
