# rvs Command Reference

Alpha command surface:

| Command | Purpose |
| --- | --- |
| `rvs auth` | Browser/device login and local profile management |
| `rvs runtime` | Local Python, Node, and Java runtime management |
| `rvs pkg` | Package repositories and package-manager configuration |
| `rvs packages` | Alias for `rvs pkg` |
| `rvs pip` | Native pip passthrough with ephemeral Ravenstash auth injection |
| `rvs uv` | Native uv passthrough with ephemeral Ravenstash auth injection |
| `rvs twine` | Native twine passthrough with ephemeral Ravenstash auth injection |
| `rvs npm` | Native npm passthrough with ephemeral Ravenstash auth injection |
| `rvs mvn` | Native Maven passthrough with ephemeral Ravenstash auth injection |
| `rvs repo` | Placeholder for future source repositories |
| `rvs ci` | Placeholder for future CI |

Removed from the alpha surface: previous experimental project lifecycle
commands, package token commands, and direct repository/token top-level
management groups.

Global options:

```bash
rvs --version
rvs --json COMMAND ...
```

`--json` emits each rvs-owned result as one JSON object. A command that emits
multiple results uses newline-delimited JSON. Native `pip`, `uv`, `twine`, `npm`,
and Maven subprocess output is not transformed.

## `rvs auth`

```bash
rvs auth login [--profile NAME] [--api-url URL] [--duration 8h] [--no-browser]
rvs auth logout [--profile NAME]
rvs auth logout --all
rvs auth status [--profile NAME]
rvs auth whoami [--profile NAME]
rvs auth profile list
rvs auth profile switch [NAME]
rvs auth profile delete [NAME]
rvs auth profile delete --all
rvs auth profile rename OLD NEW
```

Local profiles store metadata in `~/.rvs/config.toml`. Device login access and
refresh tokens are stored in the OS keyring. `RVS_TOKEN` is the automation path
and overrides local credentials; a rejected `RVS_TOKEN` is never replaced by a
stored profile credential. `rvs auth whoami` verifies identity against the
server rather than reporting local metadata as identity.

Device login discovers package endpoints from DevAPI. Non-production automation
profiles that do not log in declare the DevAPI and transfer URLs outside git
through environment variables or an ignored env file. The CLI never receives
or calls a Central package-control URL:

```bash
RVS_PROFILE_STAGING_API_URL=https://<staging-devapi-host>
RVS_PROFILE_STAGING_PKG_DOWNLOAD_URL=https://<staging-download-host>
RVS_PROFILE_STAGING_PKG_UPLOAD_URL=https://<staging-upload-host>
RVS_PROFILE_DEV_API_URL=http://<local-devapi-host>
RVS_PROFILE_DEV_PKG_DOWNLOAD_URL=http://<local-download-host>
RVS_PROFILE_DEV_PKG_UPLOAD_URL=http://<local-upload-host>
```

`rvs` reads process environment variables, a nearest `.rvs.env`, `~/.rvs/profiles.env`,
or the file pointed to by `RVS_ENV_FILE`. Process environment values have the
highest priority.

## `rvs runtime`

```bash
rvs runtime install python|node|java VERSION [--force]
rvs runtime uninstall python|node|java VERSION [--yes]
rvs runtime list
rvs runtime which python|node|java [VERSION] [--executable NAME]
rvs runtime use python|node|java VERSION
rvs runtime env
rvs runtime setup-shell [--shell bash|zsh|fish]
rvs runtime doctor
```

The runtime area is intentionally limited to Python, Node, and Java. Partial
versions resolve to the newest matching installed semantic version. Managed
shell shims resolve `.python-version`, `.node-version`, and `.java-version` at
invocation time, so project pins written by `runtime use` are effective after
the shim was installed.

## `rvs pkg` / `rvs packages`

Repository commands:

```bash
rvs pkg repo list [--profile NAME] [--customer-id CUSTOMER_ID] [--ecosystem pypi|npm|maven]
rvs pkg repo create NAME --ecosystem pypi|npm|maven [--profile NAME] [--customer-id CUSTOMER_ID] [--default]
rvs pkg repo show REPOSITORY_NAME [--profile NAME]
rvs pkg repo rename REPOSITORY_NAME NEW_NAME [--profile NAME]
rvs pkg repo delete REPOSITORY_NAME [--profile NAME] [--yes]
rvs pkg repo set-default pypi|npm|maven REPOSITORY_NAME [--profile NAME]
rvs pkg repo defaults [--profile NAME]
rvs pkg repo set-upstream REPOSITORY_NAME REMOTE_ID [--min-age-days DAYS] [--profile NAME]
rvs pkg repo clear-upstream REPOSITORY_NAME [--profile NAME]
```

Repository names use lowercase letters, numbers, and hyphens. Defaults are
stored per profile under `[profiles.<name>.registries.<ecosystem>]`; legacy
top-level `[registries.<ecosystem>]` values are still read as a fallback. Renaming a
repository also updates a matching default in the selected profile.

Remote cache & proxy commands:

```bash
rvs pkg remote-cache list [--profile NAME] [--customer-id CUSTOMER_ID] [--ecosystem pypi|npm|maven]
rvs pkg remote-cache create --ecosystem pypi|npm|maven [--profile NAME] [--customer-id CUSTOMER_ID]
rvs pkg remote-cache show CACHE_ID [--profile NAME]
rvs pkg remote-cache set-age CACHE_ID --min-age-days DAYS [--profile NAME]
rvs pkg remote-cache delete CACHE_ID [--profile NAME] [--yes]
rvs pkg remote-cache delete CACHE_ID --customer-id CUSTOMER_ID --ecosystem pypi|npm|maven [--profile NAME] [--yes]
```

Package metadata commands:

```bash
rvs pkg package list --repo REPOSITORY_NAME [--profile NAME]
rvs pkg package show NAME --repo REPOSITORY_NAME [--profile NAME]
rvs pkg package delete NAME --repo REPOSITORY_NAME [--profile NAME] [--yes]
rvs pkg package delete-version NAME VERSION --repo REPOSITORY_NAME [--profile NAME] [--yes]
rvs pkg package yank NAME VERSION --repo REPOSITORY_NAME [--reason TEXT] [--profile NAME]
```

Package listings include download and bandwidth totals. `package show` includes
per-version metrics plus artifact filenames, sizes, and SHA-256 digests.

PyPI helpers:

```bash
rvs pkg pypi index-url [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs pkg pypi upload-url [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs pkg pypi install PACKAGE... [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs pkg pypi publish [DIST_DIR] [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs pkg pypi configure [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
```

The install helper uses Ravenstash as pip's primary `PIP_INDEX_URL`. Direct
publishing sends the wheel/sdist metadata fields expected by the legacy PyPI
upload protocol, including the correct wheel Python tag or `source` marker.

npm helpers:

```bash
rvs pkg npm registry-url [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs pkg npm npmrc [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs pkg npm install PACKAGE... [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs pkg npm publish [PACKAGE_DIR] [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs pkg npm configure [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
```

Direct publishing runs native `npm pack` before sending the npm wire payload,
so npm's packlist and lifecycle behavior apply. An `npm` executable is required.

Maven helpers:

```bash
rvs pkg maven repo-url [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs pkg maven settings [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs pkg maven install GROUP:ARTIFACT:VERSION [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs pkg maven deploy FILE --group GROUP --artifact ARTIFACT --version VERSION [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs pkg maven configure [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
```

`maven deploy` requires a canonical artifact filename matching the artifact ID
and version, including valid timestamped `SNAPSHOT` forms.

No package-token command is exposed in the alpha CLI.

## Native Package-Manager Wrappers

```bash
rvs pip [--rvs-profile NAME] [--rvs-repo REPOSITORY_NAME] [--rvs-customer-id CUSTOMER_ID] [--rvs-native-config respect|override|isolate] PIP_ARGS...
rvs uv [--rvs-profile NAME] [--rvs-repo REPOSITORY_NAME] [--rvs-customer-id CUSTOMER_ID] [--rvs-native-config respect|override|isolate] UV_ARGS...
rvs twine [--rvs-profile NAME] [--rvs-repo REPOSITORY_NAME] [--rvs-customer-id CUSTOMER_ID] [--rvs-native-config respect|override|isolate] TWINE_ARGS...
rvs npm [--rvs-profile NAME] [--rvs-repo REPOSITORY_NAME] [--rvs-customer-id CUSTOMER_ID] [--rvs-native-config respect|override|isolate] NPM_ARGS...
rvs mvn [--rvs-profile NAME] [--rvs-repo REPOSITORY_NAME] [--rvs-customer-id CUSTOMER_ID] [--rvs-native-config respect|override|isolate] MVN_ARGS...
```

These commands run the named native package manager. They are not aliases for
`rvs pkg`. By default, `--rvs-native-config respect` leaves native registry
selection alone, reads native config files and relevant environment variables,
and injects short-lived Ravenstash credentials only when the invocation
references Ravenstash registry URLs.

Passing `--rvs-repo` selects a Ravenstash repository for the invocation and
overrides native registry selection. `--rvs-native-config isolate` also disables
native config where the underlying tool supports it, such as `PIP_CONFIG_FILE`
for pip and `UV_NO_CONFIG` for uv. Tokens are injected through subprocess
environment variables or temporary files and are not written to persistent
package-manager config files.

Examples:

```bash
rvs npm install @acme/widgets
rvs npm --rvs-repo internal-npm install @acme/widgets
rvs npm --rvs-repo internal-npm publish

rvs pip install acme-utils
rvs pip --rvs-repo internal-pypi install acme-utils

rvs uv sync
rvs uv --rvs-repo internal-pypi --rvs-native-config isolate sync

rvs twine --rvs-repo internal-pypi upload dist/*
rvs mvn --rvs-repo internal-maven deploy
```

## `rvs repo`

Placeholder commands:

```bash
rvs repo list
rvs repo create NAME
rvs repo clone REPO
rvs repo show REPO
rvs repo delete REPO
```

Each command exits with "rvs repo is not implemented yet."

## `rvs ci`

Placeholder commands:

```bash
rvs ci list
rvs ci run [PIPELINE]
rvs ci status [RUN_ID]
rvs ci logs RUN_ID
```

Each command exits with "rvs ci is not implemented yet."
