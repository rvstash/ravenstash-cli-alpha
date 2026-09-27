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

`rvs auth logout`, `rvs profile delete`, and `rvs profile rename` also end the
profile's device session on the Ravenstash server. If the server cannot be
reached, local credentials are still removed and `rvs` warns that the session
stays valid on the server until it expires. A saved profile keeps the
Ravenstash API it was created for, and its stored sign-in is only ever sent to
the API that issued it; to use another API, sign in with a new profile.

When a package tool must connect without an `rvs` wrapper, run `rvs art token mint --target NAMESPACE/REPOSITORY`. The `--access` and
`--duration` flags default to read and four hours. Select formats explicitly when the target enables more than one.

## Accounts and the current repository

| Command | What it does |
| --- | --- |
| `rvs account list` | Lists personal accounts and organizations you can use. |
| `rvs account switch` | Interactively chooses a personal account or organization. |
| `rvs account switch user:USERNAME` | Chooses a personal account directly by username. |
| `rvs account switch org:HANDLE` | Chooses an organization directly by its public handle. |
| `rvs account current` | Shows the selected account. |
| `rvs art select NAMESPACE/REPOSITORY` | Chooses a private repository. |
| `rvs art current` | Shows the selected repository or mirror. |
| `rvs art clear` | Clears that choice without signing out. |
| `rvs context current` | Shows the signed-in user and current choices together. |

Account resources are always displayed as `user:USERNAME` or `org:HANDLE` so
they remain distinct from unprefixed namespace names. Bare account handles are
still accepted as selectors for compatibility.

Use `--account user:USERNAME`, `--account org:HANDLE`, or `--target TARGET` on an
`rvs art` command when you want a different choice for only that command. A
repository target can be name-based (`NAMESPACE/REPOSITORY`) or ID-based
(`in/ar_...`).

## Repositories

| Command | What it does |
| --- | --- |
| `rvs art repo list` | Lists repositories. |
| `rvs art repo create NAME --format FORMAT` | Creates a repository for one or more package formats. |
| `rvs art repo show TARGET` | Shows repository details. |

Supported formats are `pypi`, `npm`, `maven`, and `oci`. Container images and
Helm charts are content types within OCI. Use commas or repeat `--format` to
enable more than one format.

## Package sources

| Command | What it does |
| --- | --- |
| `rvs art repo upstream list REPOSITORY FORMAT` | Lists the package sources used by a repository, addressed by position. |

The repository's own packages are always checked first and have no stored
position. Configured upstream positions are `1` through `4`, and gaps are
retained.

## Private mirrors

| Command | What it does |
| --- | --- |
| `rvs art mirror list` | Lists private mirrors and their `rc_...` remote-cache permanent IDs. |
| `rvs art mirror create SOURCE` | Adds a Ravenstash-provided mirror. |
| `rvs art mirror create --format FORMAT` | Adds the default mirror for a package format. |
| `rvs art mirror show REMOTE_CACHE_ID` | Shows a private mirror through its owning remote-cache permanent ID. |
| `rvs art mirror select SOURCE` | Chooses a Ravenstash-provided mirror. |
| `rvs art mirror select --custom NAME` | Chooses a custom mirror. |

## Browser-only operations

Renaming or deleting a repository, changing a repository's package sources,
changing a private mirror's package-age policy, deleting a private mirror, and
deleting a whole package are managed in the Ravenstash web app only. `rvs` can
list and show these resources, delete single package versions and OCI content,
and yank or deprecate versions.

## Packages

| Command | What it does |
| --- | --- |
| `rvs art package list` | Lists packages. |
| `rvs art package show PACKAGE` | Shows a package summary and its newest 50 versions. |
| `rvs art package show PACKAGE --limit N` | Shows the newest `N` (1–100) versions. |
| `rvs art package show PACKAGE --all-versions` | Shows every version. |
| `rvs art package show PACKAGE --version VERSION` | Shows one version with its files and their digests. |
| `rvs art package yank PACKAGE VERSION` | Yanks a PyPI version, optionally with `--reason`. |
| `rvs art package unyank PACKAGE VERSION` | Makes a yanked PyPI version selectable again. |
| `rvs art package deprecate PACKAGE VERSION --message TEXT` | Adds an npm deprecation warning. |
| `rvs art package undeprecate PACKAGE VERSION` | Clears an npm deprecation warning. |
| `rvs art package delete-version PACKAGE VERSION` | Deletes one version. |

Package commands act on the repository chosen with `rvs art select` unless you
pass `--target NAMESPACE/REPOSITORY` (or `in/ar_...`). `--format` is needed only
when that repository has more than one of pypi, npm, and maven; yank and unyank
always use pypi, and deprecate and undeprecate always use npm.

Versions are listed newest first. When more versions exist than are shown,
`package show` says so on stderr. With root `--json`, `package show` prints one
document with the `package` summary, the listed `versions`, and
`versions_next_cursor`, which is null once every version is listed; `--version`
prints one document with the version's metadata, its `file_count`, and every
one of its `files`, each carrying a `digests` object keyed by algorithm (such as
`sha256`, `sha512`, `md5`, or `blake2b_256`).

Yanking is a PyPI resolver control. npm deprecation is warning metadata and does
not prevent installation. Maven has no corresponding lifecycle operation.

## Listings and limits

Listings such as `repo list`, `mirror list`, `package list`, and `account list`
read every page from Ravenstash. Commands that take `--limit` and `--cursor`,
such as `rvs art oci list` and `rvs art evidence list`, return exactly one page
and print the cursor for the next page; with root `--json` they return the page
unchanged with its `next_cursor`.

`rvs art oci manifest list PATH` shows each manifest's newest tags and its total
tag count. `rvs art oci tag list PATH --digest sha256:DIGEST` lists every tag
that points at one manifest.

When Ravenstash asks `rvs` to slow down or is briefly unavailable, read commands
wait for the time the server asks for (up to 30 seconds) and retry a limited
number of times. Values `rvs` does not yet recognize, such as a new format,
status, or account type, are shown as Ravenstash reports them.

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
rvs oras ORAS_ARGUMENTS...
```

The commands accept `--rvs-profile`, `--rvs-account`, and `--rvs-target` where
applicable. Advanced integrations may pass a typed `--rvs-account-ref`.
Publishing commands also accept `--rvs-yes` for protected automation.

These are native-tool passthroughs rather than a second package-management API.
For example, use `rvs pip install PACKAGE`, `rvs twine upload dist/*`, `rvs npm
publish`, or `rvs mvn deploy`. Publishing commands ask for confirmation unless
`--rvs-yes` is supplied.

pnpm, Yarn, Bun, Gradle, and sbt can use Ravenstash package addresses, but there
are no `rvs pnpm`, `rvs yarn`, `rvs bun`, `rvs gradle`, or `rvs sbt` commands.

Use `rvs art reference --format oci` to print the readable
repository-qualified Ravenstash address for an image or chart. ORAS does not
take a Ravenstash content-type or format flag; the manifest determines the
content type.

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
| `rvs update --apply` | Installs the latest update in the rolling `v0` channel. |
| `rvs update --to 0.MINOR --apply` | Installs the latest stable patch in one minor line without creating a pin. |
| `rvs update --candidate X.Y.ZrcN` | Verifies and previews a signed GitHub release candidate. |
| `rvs update --candidate X.Y.ZrcN --apply` | Installs the verified candidate package. |

See the [public CLI documentation](https://docs.ravenstash.com/cli/overview/) for
task-focused guides and examples.

## Native addresses and setup

`rvs art endpoint --format FORMAT` prints labeled read and publish addresses for
repositories, or only the read address for a mirror. Add `--access read` or
`--access publish` to print one raw address for scripts. For OCI the address is
the login host; other formats return the complete native URL.
`rvs art reference [PATH[:TAG]|PATH@DIGEST] --format oci`
prints a name-based repository-qualified reference without adding a tag.
Both commands use read-only discovery and work with leaf `--target/-t`, `--account`,
and `--profile/-p` options.

`rvs art native config TOOL` prints setup snippets and commands for `pip`, `uv`,
`twine`, `npm`, `mvn` (`maven` also accepted), `docker`, `helm`, or `oras`. It does
not mint credentials, execute tools, write files, select a target, or create mirrors.
Pip always reads and Twine always publishes; both reject `--access`. Other tools
default to read + publish for repositories and read for mirrors; `--access read`
reduces the instructions. Explicit mirror publication is rejected. ORAS uses the
single enabled OCI format; `--format`, when needed, accepts `oci`.

Mint separately with `rvs art token mint --format oci --access publish`.
Repeat `--format/-f` or use comma-separated values; `--all-formats` snapshots every
enabled format on the exact repository. The selected target is used by default.
Mirrors have one format and read access. Lifetimes are 15 minutes through 12 hours,
default four hours, shortened by source expiry. `admin` adds native deletion.

Use root `--json` for one structured result. Plain endpoint/reference/token output
is one value; plain template output is a labelled document. Native wrappers keep
the native tool's output. Diagnostics go to stderr for these capture-friendly commands.

Custom mirror creation is available in the webapp. Existing custom mirrors remain
available to CLI listing, showing, and selection; age changes, deletion, and
upstream attachment are managed in the webapp.

`rvs update --to 0.MINOR` previews the latest stable patch in that minor line
without changing the active installation or its rolling `v0` channel. Add
`--apply` to install. A later plain `rvs update` resumes at the newest `v0`
release. APT installations check the signed `v0` release channel, so a new
release is reported even before the local APT package list is refreshed; `--apply`
then refreshes only the Ravenstash APT source and installs that exact version
through APT. Portable Linux, Alpine/musl, macOS, and Windows installations
download, authenticate, stage, health-check, and atomically activate the matching
native bundle. Nix, Homebrew, and WinGet installations delegate replacement to
their package manager. Homebrew and WinGet upgrade their rolling major package.
Because their catalogs cannot reliably select an older minor from that package,
an exact-minor request fails before mutation and offers the signed portable path.
Homebrew and WinGet detection is ready for
their generated manifests, but those paths become generally available only when
the manifests are accepted into their external catalogs. Because supported Nix
installs use immutable version-tag flake references, the Nix path replaces the
`ravenstash-cli` profile element with the exact selected tag and restores the
installed tag if replacement fails.
`rvs update --candidate X.Y.ZrcN` verifies a signed
GitHub prerelease for APT or portable installation; add `--apply` to install it.
`--candidate` and `--to` are mutually exclusive. `--yes/-y` requires `--apply`.

Multi-format options accept comma-separated values, repeated flags, or both:

```bash
rvs art repo create packages --format pypi,npm,maven,oci
rvs art token mint --target platform/packages -f pypi -f oci
```

Whitespace is trimmed and duplicates are removed. Empty or unknown formats fail
before any mutation. Commands requiring one format still accept only one.
