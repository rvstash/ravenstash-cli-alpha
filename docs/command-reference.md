# rvs Command Reference

Alpha command surface:

| Command | Purpose |
| --- | --- |
| `rvs auth` | Browser/device login and credential state |
| `rvs profile` | Named local CLI profile management |
| `rvs account` | Personal/organization acting-account selection |
| `rvs context` | Effective user/profile/account/target inspection |
| `rvs runtime` | Local Python, Node, and Java runtime management |
| `rvs art` / `rvs artifacts` | Repositories for packages, container images, and Helm charts |
| `rvs pip` | Native pip passthrough with ephemeral Ravenstash auth injection |
| `rvs uv` | Native uv passthrough with ephemeral Ravenstash auth injection |
| `rvs twine` | Native twine passthrough with ephemeral Ravenstash auth injection |
| `rvs npm` | Native npm passthrough with ephemeral Ravenstash auth injection |
| `rvs mvn` | Native Maven passthrough with ephemeral Ravenstash auth injection |
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
rvs auth login [--profile NAME] [--duration 8h] [--no-browser]
  [--credential-store auto|keyring|pass|vault|plaintext] [--allow-insecure-storage]
rvs auth logout [--profile NAME]
rvs auth logout --all
rvs auth status [--profile NAME]
rvs auth whoami [--profile NAME]
rvs auth storage doctor [--profile NAME]
rvs auth storage setup [--store vault|plaintext] [--allow-insecure-storage]
rvs auth storage set auto|keyring|pass|vault|plaintext
rvs auth storage unlock
rvs auth storage lock
rvs auth storage change-passphrase
```

`rvs auth status` reports only local credential state. `rvs auth whoami` verifies
and reports only the authenticated Ravenstash user.

Local profiles store metadata in `~/.rvs/config.toml`. Device login access and
refresh tokens use an OS keyring, initialized `pass`, or the passphrase-encrypted
Ravenstash vault. If none exists, first login asks whether to install the dedicated
Ravenstash encrypted vault before opening device authorization. This onboarding
prompt is yes/no and names the installed store. Plaintext storage is available
only through the advanced storage options after an exact risk acknowledgement and
is never selected automatically. `RVS_TOKEN` is the
automation path and overrides local credentials; a rejected `RVS_TOKEN` is never
replaced by a stored profile credential. `rvs auth whoami` verifies identity
against the server rather than reporting local metadata as identity.

Vault passphrases require at least 8 characters. The CLI recommends 12+ characters
or a short multi-word passphrase and warns when an accepted passphrase is shorter.

Device login discovers package endpoints from DevAPI. The CLI never receives or
calls a Central package-control URL.

## `rvs profile`

```bash
rvs profile list
rvs profile current [--profile NAME] [--verbose]
rvs profile use [NAME]
rvs profile delete [NAME]
rvs profile delete --all
rvs profile rename OLD NEW
```

A local profile is a named CLI configuration. It associates one DevAPI endpoint,
one credential slot, discovered package endpoints, and cached context; it is not
the authenticated user or the acting account. `current` reports non-secret local
configuration and the source of the effective selection.

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

## Acting account and combined context

```bash
rvs account list [--profile NAME]
rvs account current [--profile NAME]
rvs account use HANDLE|personal|org:LABEL|STABLE_REF [--profile NAME]
rvs context current [--profile NAME]

rvs art select TARGET [--kind KIND] [--account ACCOUNT] [--profile NAME]
rvs art current [--account ACCOUNT] [--profile NAME]
rvs art clear [--account ACCOUNT] [--profile NAME]
rvs art --target TARGET [--account ACCOUNT] [--kind KIND] install PACKAGE...
```

The authenticated user is the audit actor. The acting account is the personal or
organization customer used for authorization, ownership, and metering. A package
target is selected inside that account. `rvs context current` verifies and shows
the effective tuple and selection provenance without collapsing those concepts.

Repository targets are `namespace/repository` in the acting account.
Realm prefixes and `@` notation are rejected. `rvs art --scope self` is the
default; `--scope public` or `--public` currently fails with
`PublicCatalogUnavailable` before any resource operation. Mirrors remain
separate targets: `mirror:official-slug` or `custom-mirror:customer-name`.
Resolution is always scoped to the acting account. `--kind` is needed only when
a generic operation or duplicate cross-kind custom mirror name is ambiguous.
Clearing a target does not change the login or account.

## CLI updates

`rvs update` checks only the signed candidate in the currently configured APT
compatibility channel. `rvs update --apply` refreshes APT metadata and installs
that compatible candidate. It never changes channels.

Use `rvs upgrade --to 0.7` (or a later channel) to make a breaking compatibility
transition explicit. The command authenticates Ravenstash's signed channel
manifest, shows the migration notes, asks for confirmation, changes the APT
source atomically, and restores the prior source if authentication or candidate
validation fails.

## `rvs art`

Publishing requires confirmation of the resolved repository, acting account, and artifacts.
Use `--yes` (`-y`) with `rvs art pypi publish`, `rvs art npm publish`, or
`rvs art maven deploy` to skip confirmation. Native wrappers accept `--rvs-yes`
(for example, `rvs npm --rvs-yes --rvs-target platform/backend publish`).
Unattended publishing must pass the bypass flag. Native builds show their project
or supplied references because the final artifacts may be produced during execution.

Preview identity examples:

| Format | Heading | Details |
| --- | --- | --- |
| PyPI | `PyPI acme-sdk==1.4.0` | Selected wheel/sdist filenames, grouped by name/version |
| npm | `npm @acme/sdk@1.4.0` | Tarball or planned packing source; tag when known |
| Maven | `Maven com.acme:sdk:1.4.0` | JAR/POM/classifier files; direct deployment also lists checksum sidecars |
| Container | `Container oci.rvsta.sh/platform/backend/api:1.4.0` | Supplied reference and explicit platforms |
| Helm | `Helm oci://oci.rvsta.sh/platform/backend/api-chart:1.4.0` | Chart archive; name/version read from `Chart.yaml` |

The final question is `Publish these N files?` for a known file inventory, or
`Publish these files/references?` when a native tool resolves the final output.
Metadata that cannot be read is labeled unavailable, rather than inferred from a
potentially renamed archive. Native build/project previews do not claim to enumerate
future output or resolve all native configuration. Helm version build metadata uses
`_` in OCI tags in place of `+`.

Repository commands:

```bash
rvs art repo list [--profile NAME] [--customer-id CUSTOMER_ID] [--registry-kind pypi|npm|maven|container|helm]
rvs art repo create [NAMESPACE/]NAME --registry-kind pypi|npm|maven|container|helm [--profile NAME] [--customer-id CUSTOMER_ID] [--default]
rvs art repo show REPOSITORY_NAME [--profile NAME]
rvs art repo rename REPOSITORY_NAME NEW_NAME [--profile NAME]
rvs art repo delete REPOSITORY_NAME [--profile NAME] [--yes]
rvs art repo set-default pypi|npm|maven|container|helm REPOSITORY_NAME [--profile NAME]
rvs art repo defaults [--profile NAME]
rvs art repo upstream list REPOSITORY KIND [--profile NAME]
rvs art repo upstream add REPOSITORY KIND --private-repository NAMESPACE/REPOSITORY [--priority N] [--min-age-hours HOURS] [--max-age-hours HOURS] [--profile NAME]
rvs art repo upstream add REPOSITORY KIND --remote-cache CACHE [--priority N] [--min-age-hours HOURS] [--max-age-hours HOURS] [--profile NAME]
rvs art repo upstream update REPOSITORY KIND ATTACHMENT [--priority N] [--min-age-hours HOURS] [--max-age-hours HOURS] [--profile NAME]
rvs art repo upstream reorder REPOSITORY KIND ATTACHMENT... [--profile NAME]
rvs art repo upstream remove REPOSITORY KIND ATTACHMENT [--profile NAME]
```

`--registry-kind` (short form `-k`) is the registry-kind selector.

Repository names use lowercase letters, numbers, and hyphens. Defaults are
stored per profile under `[profiles.<name>.registries.<registry-kind>]`; legacy
top-level `[registries.<registry-kind>]` values are still read as a fallback. Renaming a
repository also updates a matching default in the selected profile.

Container and Helm are OCI-native private lanes. They do not support upstream
attachments or remote caches. Classic non-OCI Helm repositories are not
supported.

The `upstream` subgroup manages the complete ordered plan of at most four mixed
private and remote sources. A private selector may be namespace-qualified and must
resolve to a same-customer, same-kind lane. Omitting `--priority` appends. Private
sources default to a disabled minimum-age guard; remote sources retain their server
recommendation when the option is omitted. Reordering replaces the full order
atomically.

Private mirror commands:

```bash
rvs art mirror list [--profile NAME] [--customer-id CUSTOMER_ID] [--registry-kind pypi|npm|maven]
rvs art mirror create --registry-kind pypi|npm|maven [--profile NAME] [--customer-id CUSTOMER_ID]
rvs art mirror show CACHE_ID [--profile NAME]
rvs art mirror set-age CACHE_ID --min-age-hours HOURS [--profile NAME]
rvs art mirror delete CACHE_ID [--profile NAME] [--yes]
rvs art mirror delete CACHE_ID --customer-id CUSTOMER_ID --registry-kind pypi|npm|maven [--profile NAME] [--yes]
rvs art mirror add OFFICIAL_SOURCE [--select]
rvs art mirror create-custom NAME --kind pypi|npm|maven --api-url URL --publication-control user-controlled|externally-controlled [--artifact-url URL] [--select]
rvs art mirror select SOURCE
rvs art mirror select --custom NAME [--kind KIND]
rvs art mirror current
rvs art mirror clear
```

Repository upstream configuration continues to use `--remote-cache`
because it attaches the backing cache rather than the direct private mirror.

Package metadata commands:

```bash
rvs art package list --repo REPOSITORY_NAME --registry-kind pypi|npm|maven [--profile NAME]
rvs art package show NAME --repo REPOSITORY_NAME --registry-kind pypi|npm|maven [--profile NAME]
rvs art package delete NAME --repo REPOSITORY_NAME --registry-kind pypi|npm|maven [--profile NAME] [--yes]
rvs art package delete-version NAME VERSION --repo REPOSITORY_NAME --registry-kind pypi|npm|maven [--profile NAME] [--yes]
rvs art package yank NAME VERSION --repo REPOSITORY_NAME --registry-kind pypi|npm|maven [--reason TEXT] [--profile NAME]
```

Package listings include download and bandwidth totals. `package show` includes
per-version metrics plus artifact filenames, sizes, and SHA-256 digests.

PyPI helpers:

```bash
rvs art pypi index-url [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs art pypi upload-url [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs art pypi install PACKAGE... [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs art pypi publish [DIST_DIR] [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID] [--yes|-y]
rvs art pypi configure [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
```

The install helper uses Ravenstash as pip's primary `PIP_INDEX_URL`. Direct
publishing sends the wheel/sdist metadata fields expected by the legacy PyPI
upload protocol, including the correct wheel Python tag or `source` marker.

npm helpers:

```bash
rvs art npm registry-url [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs art npm npmrc [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs art npm install PACKAGE... [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs art npm publish [PACKAGE_DIR] [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID] [--yes|-y]
rvs art npm configure [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
```

Direct publishing runs native `npm pack` before sending the npm wire payload,
so npm's packlist and lifecycle behavior apply. An `npm` executable is required.

Maven helpers:

```bash
rvs art maven repo-url [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs art maven settings [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs art maven install GROUP:ARTIFACT:VERSION [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
rvs art maven deploy FILE --group GROUP --artifact ARTIFACT --version VERSION [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID] [--yes|-y]
rvs art maven configure [--repo REPOSITORY_NAME] [--profile NAME] [--customer-id CUSTOMER_ID]
```

`maven deploy` requires a canonical artifact filename matching the artifact ID
and version, including valid timestamped `SNAPSHOT` forms.

No package-token command is exposed in the alpha CLI.

## Native Package-Manager Wrappers

```bash
rvs pip [--rvs-profile NAME] [--rvs-target TARGET] [--rvs-account ACCOUNT] [--rvs-customer-id CUSTOMER_ID] [--rvs-native-config respect|override|isolate] PIP_ARGS...
rvs uv [--rvs-profile NAME] [--rvs-target TARGET] [--rvs-account ACCOUNT] [--rvs-customer-id CUSTOMER_ID] [--rvs-native-config respect|override|isolate] UV_ARGS...
rvs twine [--rvs-profile NAME] [--rvs-target TARGET] [--rvs-account ACCOUNT] [--rvs-customer-id CUSTOMER_ID] [--rvs-native-config respect|override|isolate] TWINE_ARGS...
rvs npm [--rvs-profile NAME] [--rvs-target TARGET] [--rvs-account ACCOUNT] [--rvs-customer-id CUSTOMER_ID] [--rvs-native-config respect|override|isolate] NPM_ARGS...
rvs mvn [--rvs-profile NAME] [--rvs-target TARGET] [--rvs-account ACCOUNT] [--rvs-customer-id CUSTOMER_ID] [--rvs-native-config respect|override|isolate] MVN_ARGS...
rvs docker [--rvs-profile NAME] [--rvs-target TARGET] [--rvs-account ACCOUNT] [--rvs-customer-id CUSTOMER_ID] DOCKER_ARGS...
rvs helm [--rvs-profile NAME] [--rvs-target TARGET] [--rvs-account ACCOUNT] [--rvs-customer-id CUSTOMER_ID] HELM_ARGS...
rvs oras --rvs-kind container|helm [--rvs-profile NAME] [--rvs-target TARGET] [--rvs-account ACCOUNT] [--rvs-customer-id CUSTOMER_ID] ORAS_ARGS...
rvs oci-reference --kind container|helm [--target TARGET] [--account ACCOUNT] [--oci-path PATH] [--reference TAG_OR_DIGEST] [--profile NAME] [--customer-id CUSTOMER_ID]
```

These commands run the named native package manager. They are not aliases for
`rvs art`. By default, `--rvs-native-config respect` leaves native registry
selection alone, reads native config files and relevant environment variables,
and injects short-lived Ravenstash credentials only when the invocation
references Ravenstash registry URLs.

Passing `--rvs-target` selects a private repository or private mirror for one
invocation and overrides the saved selection. `--rvs-native-config isolate` also disables
native config where the underlying tool supports it, such as `PIP_CONFIG_FILE`
for pip and `UV_NO_CONFIG` for uv. Tokens are injected through subprocess
environment variables or temporary files and are not written to persistent
package-manager config files.

Examples:

```bash
rvs npm install @acme/widgets
rvs npm --rvs-target acme/internal-npm install @acme/widgets
rvs npm --rvs-target acme/internal-npm publish

rvs pip install acme-utils
rvs pip --rvs-target acme/internal-pypi install acme-utils

rvs uv sync
rvs uv --rvs-target acme/internal-pypi --rvs-native-config isolate sync

rvs twine --rvs-target acme/internal-pypi upload dist/*
rvs mvn --rvs-target acme/internal-maven deploy

rvs docker --rvs-target acme/runtime-images pull oci.rvsta.sh/acme/runtime-images/api:latest
rvs helm --rvs-target acme/deployment-charts show chart oci://oci.rvsta.sh/acme/deployment-charts/charts/api --version 1.2.3
rvs oras --rvs-kind container --rvs-target acme/runtime-images discover oci.rvsta.sh/acme/runtime-images/api:latest
rvs oci-reference --kind container --target acme/runtime-images --oci-path api --reference latest
```

The OCI wrappers always scope one invocation to one exact logical repository.
They obtain a short-lived Container or Helm capability through DevAPI, preserve
unrelated native registry credentials in an ephemeral config copy, and install
an exact-host `docker-credential-rvs` helper only in that copy. Secrets are not
placed in argv and the user's Docker or Helm config is never rewritten. Docker,
Helm, and ORAS share `oci.rvsta.sh`; `/v2/` is protocol plumbing used by the
native clients and is not part of the documented repository reference.

## `rvs ci`

Placeholder commands:

```bash
rvs ci list
rvs ci run [PIPELINE]
rvs ci status [RUN_ID]
rvs ci logs RUN_ID
```

Each command exits with "rvs ci is not implemented yet."
