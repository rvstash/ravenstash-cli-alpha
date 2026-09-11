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
| `rvs art repo create NAME --registry-kind FORMAT` | Creates a repository for one or more package formats. |
| `rvs art repo show NAME` | Shows repository details. |
| `rvs art repo rename OLD NEW` | Renames a repository. |
| `rvs art repo delete NAME` | Deletes a repository after confirmation. |
| `rvs art repo set-default FORMAT NAME` | Chooses the default repository for a package format. |
| `rvs art repo defaults` | Lists the current defaults. |

Supported formats are `pypi`, `npm`, `maven`, `container`, and `helm`. Repeat
`--registry-kind` to create a repository that supports more than one format.

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
| `rvs art mirror add SOURCE` | Adds a Ravenstash-provided mirror. |
| `rvs art mirror create --registry-kind FORMAT` | Adds the default mirror for a package format. |
| `rvs art mirror create-custom NAME` | Adds a custom HTTPS package source. |
| `rvs art mirror show MIRROR_ID` | Shows a mirror. |
| `rvs art mirror set-age MIRROR_ID --min-age-hours HOURS` | Delays newly published packages for the chosen time. |
| `rvs art mirror delete MIRROR_ID` | Deletes a mirror after confirmation. |
| `rvs art mirror select SOURCE` | Chooses a Ravenstash-provided mirror. |
| `rvs art mirror select --custom NAME` | Chooses a custom mirror. |

## Packages

| Command | What it does |
| --- | --- |
| `rvs art package list --repo NAME --registry-kind FORMAT` | Lists packages. |
| `rvs art package show PACKAGE --repo NAME --registry-kind FORMAT` | Shows a package and its versions. |
| `rvs art package yank PACKAGE VERSION --repo NAME --registry-kind FORMAT` | Marks a version as withdrawn. |
| `rvs art package delete-version PACKAGE VERSION --repo NAME --registry-kind FORMAT` | Deletes one version. |
| `rvs art package delete PACKAGE --repo NAME --registry-kind FORMAT` | Deletes a package and all its versions. |

## PyPI, npm, and Maven helpers

| Command | What it does |
| --- | --- |
| `rvs art pypi install PACKAGE...` | Installs Python packages. |
| `rvs art pypi publish DIST_DIR` | Publishes Python package files. |
| `rvs art pypi index-url` | Prints the private install address. |
| `rvs art pypi upload-url` | Prints the private upload address. |
| `rvs art npm install PACKAGE...` | Installs npm packages. |
| `rvs art npm publish PACKAGE_DIR` | Publishes an npm package. |
| `rvs art npm registry-url` | Prints the private npm address. |
| `rvs art maven install GROUP:ARTIFACT:VERSION` | Downloads a Maven package. |
| `rvs art maven deploy FILE --group GROUP --artifact ARTIFACT --version VERSION` | Publishes a Maven package. |
| `rvs art maven repo-url` | Prints the private Maven address. |

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
rvs oras --rvs-kind container|helm ORAS_ARGUMENTS...
```

The commands accept `--rvs-profile`, `--rvs-account`, and `--rvs-target` where
applicable. Publishing commands also accept `--rvs-yes` for protected automation.

pnpm, Yarn, Bun, Gradle, and sbt can use Ravenstash package addresses, but there
are no `rvs pnpm`, `rvs yarn`, `rvs bun`, `rvs gradle`, or `rvs sbt` commands.

Use `rvs oci-reference --kind container|helm` to print the permanent Ravenstash
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
| `rvs upgrade --to SERIES` | Moves to a newer release series after confirmation. |

See the [public CLI documentation](https://docs.ravenstash.com/cli/overview/) for
task-focused guides and examples.
