# rvn Command Reference

Alpha command surface:

| Command | Purpose |
| --- | --- |
| `rvn auth` | Browser/device login and local profile management |
| `rvn runtime` | Local Python, Node, and Java runtime management |
| `rvn pkg` | Package repositories and package-manager configuration |
| `rvn packages` | Alias for `rvn pkg` |
| `rvn pip` | Native pip passthrough with ephemeral Ravenstash auth injection |
| `rvn uv` | Native uv passthrough with ephemeral Ravenstash auth injection |
| `rvn twine` | Native twine passthrough with ephemeral Ravenstash auth injection |
| `rvn npm` | Native npm passthrough with ephemeral Ravenstash auth injection |
| `rvn mvn` | Native Maven passthrough with ephemeral Ravenstash auth injection |
| `rvn repo` | Placeholder for future source repositories |
| `rvn ci` | Placeholder for future CI |

Removed from the alpha surface: previous experimental project lifecycle
commands, package token commands, and direct repository/token top-level
management groups.

## `rvn auth`

```bash
rvn auth login [--profile NAME] [--api-url URL] [--duration 8h] [--no-browser]
rvn auth logout [--profile NAME]
rvn auth logout --all
rvn auth status [--profile NAME]
rvn auth whoami [--profile NAME]
rvn auth profile list
rvn auth profile switch [NAME]
rvn auth profile delete [NAME]
rvn auth profile delete --all
rvn auth profile rename OLD NEW
```

Local profiles store metadata in `~/.rvn/config.toml`. Device login access and
refresh tokens are stored in the OS keyring. `RVN_TOKEN` is the automation path
and overrides local credentials.

Non-production profile API URLs are declared outside git through environment
variables or an ignored env file:

```bash
RVN_PROFILE_STAGING_API_URL=https://<staging-devapi-host>
RVN_PROFILE_DEV_API_URL=http://<local-devapi-host>
```

`rvn` reads process environment variables, a nearest `.rvn.env`, `~/.rvn/profiles.env`,
or the file pointed to by `RVN_ENV_FILE`. Process environment values have the
highest priority.

## `rvn runtime`

```bash
rvn runtime install python VERSION [--force]
rvn runtime install node VERSION [--force]
rvn runtime install java VERSION [--force]
rvn runtime uninstall python VERSION
rvn runtime list
rvn runtime which python [VERSION]
rvn runtime use python VERSION
rvn runtime env
rvn runtime setup-shell
rvn runtime doctor
```

The runtime area is intentionally limited to Python, Node, and Java.

## `rvn pkg` / `rvn packages`

Repository commands:

```bash
rvn pkg repo list [--customer-id CUSTOMER] [--kind pypi|npm|maven]
rvn pkg repo create NAME --kind pypi|npm|maven [--customer-id CUSTOMER] [--default]
rvn pkg repo show REPOSITORY_NAME
rvn pkg repo delete REPOSITORY_NAME
rvn pkg repo set-default pypi|npm|maven REPOSITORY_NAME
rvn pkg repo defaults
```

Repository names use lowercase letters, numbers, and hyphens.

Package metadata commands:

```bash
rvn pkg package list --repo REPOSITORY_NAME
rvn pkg package show NAME --repo REPOSITORY_NAME
rvn pkg package delete NAME --repo REPOSITORY_NAME
rvn pkg package delete-version NAME VERSION --repo REPOSITORY_NAME
rvn pkg package yank NAME VERSION --repo REPOSITORY_NAME [--reason TEXT]
```

PyPI helpers:

```bash
rvn pkg pypi index-url [--repo REPOSITORY_NAME]
rvn pkg pypi upload-url [--repo REPOSITORY_NAME]
rvn pkg pypi install PACKAGE... [--repo REPOSITORY_NAME]
rvn pkg pypi publish [DIST_DIR] [--repo REPOSITORY_NAME]
rvn pkg pypi configure [--repo REPOSITORY_NAME]
```

npm helpers:

```bash
rvn pkg npm registry-url [--repo REPOSITORY_NAME]
rvn pkg npm npmrc [--repo REPOSITORY_NAME]
rvn pkg npm install PACKAGE... [--repo REPOSITORY_NAME]
rvn pkg npm publish [PACKAGE_DIR] [--repo REPOSITORY_NAME]
rvn pkg npm configure [--repo REPOSITORY_NAME]
```

Maven helpers:

```bash
rvn pkg maven repo-url [--repo REPOSITORY_NAME]
rvn pkg maven settings [--repo REPOSITORY_NAME]
rvn pkg maven install GROUP:ARTIFACT:VERSION [--repo REPOSITORY_NAME]
rvn pkg maven deploy FILE --group GROUP --artifact ARTIFACT --version VERSION [--repo REPOSITORY_NAME]
rvn pkg maven configure [--repo REPOSITORY_NAME]
```

No package-token command is exposed in the alpha CLI.

## Native Package-Manager Wrappers

```bash
rvn pip [--rvn-profile NAME] [--rvn-repo REPOSITORY_NAME] [--rvn-customer-pid PID] [--rvn-native-config respect|override|isolate] PIP_ARGS...
rvn uv [--rvn-profile NAME] [--rvn-repo REPOSITORY_NAME] [--rvn-customer-pid PID] [--rvn-native-config respect|override|isolate] UV_ARGS...
rvn twine [--rvn-profile NAME] [--rvn-repo REPOSITORY_NAME] [--rvn-customer-pid PID] [--rvn-native-config respect|override|isolate] TWINE_ARGS...
rvn npm [--rvn-profile NAME] [--rvn-repo REPOSITORY_NAME] [--rvn-customer-pid PID] [--rvn-native-config respect|override|isolate] NPM_ARGS...
rvn mvn [--rvn-profile NAME] [--rvn-repo REPOSITORY_NAME] [--rvn-customer-pid PID] [--rvn-native-config respect|override|isolate] MVN_ARGS...
```

These commands run the named native package manager. They are not aliases for
`rvn pkg`. By default, `--rvn-native-config respect` leaves native registry
selection alone, reads native config files and relevant environment variables,
and injects short-lived Ravenstash credentials only when the invocation
references Ravenstash registry URLs.

Passing `--rvn-repo` selects a Ravenstash repository for the invocation and
overrides native registry selection. `--rvn-native-config isolate` also disables
native config where the underlying tool supports it, such as `PIP_CONFIG_FILE`
for pip and `UV_NO_CONFIG` for uv. Tokens are injected through subprocess
environment variables or temporary files and are not written to persistent
package-manager config files.

Examples:

```bash
rvn npm install @acme/widgets
rvn npm --rvn-repo internal-npm install @acme/widgets
rvn npm --rvn-repo internal-npm publish

rvn pip install acme-utils
rvn pip --rvn-repo internal-pypi install acme-utils

rvn uv sync
rvn uv --rvn-repo internal-pypi --rvn-native-config isolate sync

rvn twine --rvn-repo internal-pypi upload dist/*
rvn mvn --rvn-repo internal-maven deploy
```

## `rvn repo`

Placeholder commands:

```bash
rvn repo list
rvn repo create NAME
rvn repo clone REPO
rvn repo show REPO
rvn repo delete REPO
```

Each command exits with "rvn repo is not implemented yet."

## `rvn ci`

Placeholder commands:

```bash
rvn ci list
rvn ci run [PIPELINE]
rvn ci status [RUN_ID]
rvn ci logs RUN_ID
```

Each command exits with "rvn ci is not implemented yet."
