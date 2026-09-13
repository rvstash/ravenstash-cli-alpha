# `rvs` command reference

Run `rvs COMMAND --help` for every option accepted by an installed version.

## Sign-in and profiles

| Command | What it does |
| --- | --- |
| `rvs auth login` | Signs in through a browser. |
| `rvs auth logout` | Signs out of the selected profile. |
| `rvs auth logout --all` | Signs out of every local profile. |
| `rvs auth status` | Shows whether local sign-in information is available. |
| `rvs auth whoami` | Shows the signed-in Ravenstash user. |
| `rvs auth storage doctor` | Checks whether sign-in information can be saved securely. |
| `rvs auth storage setup` | Sets up secure local storage. |
| `rvs profile list` | Lists local profiles. |
| `rvs profile current` | Shows the selected profile. |
| `rvs profile use NAME` | Selects a profile. |
| `rvs profile rename OLD NEW` | Renames a profile. |
| `rvs profile delete NAME` | Deletes a local profile. |

When a package tool must connect without an `rvs` wrapper, run `rvs art token mint --target NAMESPACE/REPOSITORY`. The `--access` and
`--duration` flags default to read and four hours. Select formats explicitly when the target enables more than one.

## Accounts and the current repository

| Command | What it does |
| --- | --- |
| `rvs account list` | Lists personal accounts and organizations you can use. |
| `rvs account use NAME` | Chooses an account by username or organization handle. |
| `rvs account current` | Shows the selected account. |
| `rvs art select NAMESPACE/REPOSITORY` | Chooses a private repository. |
| `rvs art current` | Shows the selected repository or mirror. |
| `rvs art clear` | Clears that choice without signing out. |
| `rvs context current` | Shows the signed-in user and current choices together. |

For a personal account, `NAME` is the Ravenstash username. For an organization,
it is the organization's public handle.

Use `--account NAME` or `--target NAMESPACE/REPOSITORY` on an `rvs art` command
when you want a different choice for only that command.

## Repositories

| Command | What it does |
| --- | --- |
| `rvs art repo list` | Lists repositories. |
| `rvs art repo create NAME --format FORMAT` | Creates a repository for one or more package formats. |
| `rvs art repo show NAME` | Shows repository details. |
| `rvs art repo rename OLD NEW` | Renames a repository. |
| `rvs art repo delete NAME` | Deletes a repository after confirmation. |
| `rvs art repo set-default FORMAT NAME` | Chooses the default repository for a package format. |
| `rvs art repo defaults` | Lists the current defaults. |

Supported formats are `pypi`, `npm`, `maven`, `container`, and `helm`. Use commas
or repeat `--format` to enable more than one.

## Package sources

| Command | What it does |
| --- | --- |
| `rvs art repo upstream list REPOSITORY FORMAT` | Lists the package sources used by a repository. |
| `rvs art repo upstream add REPOSITORY FORMAT --private-repository NAMESPACE/REPOSITORY` | Adds another private repository as a source. |
| `rvs art repo upstream add REPOSITORY FORMAT --mirror MIRROR_ID` | Adds a private mirror as a source. |
| `rvs art repo upstream update REPOSITORY FORMAT SOURCE_ID` | Changes a source's order or package-age settings. |
| `rvs art repo upstream reorder REPOSITORY FORMAT SOURCE_ID...` | Sets the complete source order. |
| `rvs art repo upstream remove REPOSITORY FORMAT SOURCE_ID` | Removes a source. |

## Private mirrors

| Command | What it does |
| --- | --- |
| `rvs art mirror list` | Lists private mirrors. |
| `rvs art mirror create SOURCE` | Adds a Ravenstash-provided mirror. |
| `rvs art mirror create --format FORMAT` | Adds the default mirror for a package format. |
| `rvs art mirror show MIRROR_ID` | Shows a mirror. |
| `rvs art mirror set-age MIRROR_ID --min-age-hours HOURS` | Delays newly published packages for the chosen time. |
| `rvs art mirror delete MIRROR_ID` | Deletes a mirror after confirmation. |
| `rvs art mirror select SOURCE` | Chooses a Ravenstash-provided mirror. |
| `rvs art mirror select --custom NAME` | Chooses a custom mirror. |

## Packages

| Command | What it does |
| --- | --- |
| `rvs art package list --target NAME --format FORMAT` | Lists packages. |
| `rvs art package show PACKAGE --target NAME --format FORMAT` | Shows a package and its versions. |
| `rvs art package yank PACKAGE VERSION --target NAME --format FORMAT` | Marks a version as withdrawn. |
| `rvs art package delete-version PACKAGE VERSION --target NAME --format FORMAT` | Deletes one version. |
| `rvs art package delete PACKAGE --target NAME --format FORMAT` | Deletes a package and all its versions. |

## PyPI, npm, and Maven helpers

| Command | What it does |
| --- | --- |
| `rvs art pypi install PACKAGE...` | Installs Python packages. |
| `rvs art pypi publish DIST_DIR` | Publishes Python package files. |
| `rvs art npm install PACKAGE...` | Installs npm packages. |
| `rvs art npm publish PACKAGE_DIR` | Publishes an npm package. |
| `rvs art maven install GROUP:ARTIFACT:VERSION` | Downloads a Maven package. |
| `rvs art maven publish FILE --group-id GROUP --artifact-id ARTIFACT --version VERSION` | Publishes a Maven package. |

The publishing commands ask for confirmation. Add `--yes` only in a protected
automation job.

## Package-tool commands

`rvs` can run these tools with temporary Ravenstash access:

```bash
rvs pip PIP_ARGUMENTS...
rvs uv UV_ARGUMENTS...
rvs twine TWINE_ARGUMENTS...
rvs npm NPM_ARGUMENTS...
rvs mvn MAVEN_ARGUMENTS...
rvs docker DOCKER_ARGUMENTS...
rvs helm HELM_ARGUMENTS...
rvs oras --rvs-format container|helm ORAS_ARGUMENTS...
```

The commands accept `--rvs-profile`, `--rvs-account`, and `--rvs-target` where
applicable. Publishing commands also accept `--rvs-yes` for protected automation.

pnpm, Yarn, Bun, Gradle, and sbt can use Ravenstash package addresses, but there
are no `rvs pnpm`, `rvs yarn`, `rvs bun`, `rvs gradle`, or `rvs sbt` commands.

Use `rvs art reference --format container|helm` to print the readable repository-qualified Ravenstash
address for an image or chart.

## Local runtimes and CLI updates

| Command | What it does |
| --- | --- |
| `rvs runtime install RUNTIME VERSION` | Installs Python, Node.js, or Java. |
| `rvs runtime uninstall RUNTIME VERSION` | Removes an installed runtime. |
| `rvs runtime list` | Lists installed runtimes. |
| `rvs runtime which RUNTIME` | Shows an installed runtime's program path. |
| `rvs runtime use RUNTIME VERSION` | Chooses a runtime for the current project. |
| `rvs runtime setup-shell` | Makes installed runtimes available in future shells. |
| `rvs runtime doctor` | Checks the runtime setup. |
| `rvs update` | Checks for a CLI update. |
| `rvs update --apply` | Installs an update in the current release series. |
| `rvs update --to SERIES --apply` | Moves to a newer release series after confirmation. |

See the [public CLI documentation](https://docs.ravenstash.com/cli/overview/) for
task-focused guides and examples.

## Native addresses and setup

`rvs art endpoint --format FORMAT [--access read|publish]` prints one address.
For Container/Helm this is the login host; other formats return the complete native
URL. Read is the default. `rvs art reference [PATH[:TAG]|PATH@DIGEST] --format
container|helm` prints a readable repository-qualified reference without adding a tag.
Both commands use read-only discovery and work with leaf `--target/-t`, `--account`,
and `--profile/-p` options.

`rvs art native config TOOL` prints setup snippets and commands for `pip`, `uv`,
`twine`, `npm`, `mvn` (`maven` also accepted), `docker`, `helm`, or `oras`. It does
not mint credentials, execute tools, write files, select a target, or create mirrors.
Pip always reads and Twine always publishes; both reject `--access`. Other tools
default to read + publish for repositories and read for mirrors; `--access read`
reduces the instructions. Explicit mirror publication is rejected. ORAS defaults
to all enabled OCI formats, or accepts `--format container|helm`.

Mint separately with `rvs art token mint --format container,helm --access publish`.
Repeat `--format/-f` or use comma-separated values; `--all-formats` snapshots every
enabled format on the exact repository. The selected target is used by default.
Mirrors have one format and read access. Lifetimes are 15 minutes through 12 hours,
default four hours, shortened by source expiry. `admin` adds native deletion.

Use root `--json` for one structured result. Plain endpoint/reference/token output
is one value; plain template output is a labelled document. Native wrappers keep
the native tool's output. Diagnostics go to stderr for these capture-friendly commands.

Custom mirror creation is available in the webapp. Existing custom mirrors remain
available to CLI listing, selection, age changes, deletion, and upstream attachment.

`rvs update --to SERIES` previews the selected newer release series without changing
the active APT source. Add `--apply` to install. `--yes/-y` requires `--apply`.

Multi-format options accept comma-separated values, repeated flags, or both:

```bash
rvs art repo create packages --format pypi,npm,maven,container,helm
rvs art token mint --target platform/packages -f container -f helm
```

Whitespace is trimmed and duplicates are removed. Empty or unknown formats fail
before any mutation. Commands requiring one format still accept only one.
