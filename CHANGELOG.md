# Changelog

All notable user-facing changes to `rvs` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `rvs update` rejects a release signature whose armor contains non-ASCII
  text as invalid, instead of stopping with an internal error.
- The `docker-credential-rvs` helper follows the Docker credential-helper
  protocol: errors are reported on stdout, where Docker reads them; other
  registries get the standard "credentials not found" answer, so Docker
  continues without credentials and prints no stray message; and failures no
  longer show file paths or parser details.
- `rvs runtime install node latest` installs the newest Node.js release
  instead of failing, and a version that does not exist, such as `22.99`, is
  reported instead of silently installing another release of that major.
- `rvs update` recognizes installations made with winget on Windows.
- On Windows, a second `rvs update` started while one is running reports that
  an update is already in progress instead of failing with a file error.

## [0.14.13] - 2026-09-27

### Added

- `rvs status` shows who is signed in, the profile, the acting account, the
  selected Artifacts target, and the Ravenstash API. `rvs art status` shows
  the account, repository or mirror, and format that `rvs art` commands use.
  Both only read and never select or save anything.
- `rvs` warns once per run, on stderr, when Ravenstash reports that an API this
  release uses is deprecated, and shows the date it stops working when known.
  Run `rvs update` to check for a newer release.

### Changed

- With a personal access token or organization automation token in
  `RVS_TOKEN`, commands act for the account that owns the token, so CI jobs no
  longer need `RVS_ACCOUNT_REF` or `rvs account switch`. A saved or shell
  selection does not apply while the token is set, and an `RVS_ACCOUNT_REF`
  naming another account stops the command with an explanation.
- People and accounts are shown by public handle and name, such as
  `user:ada (Ada Lovelace)` or `org:acme (Acme Inc)`, instead of by email.
  `rvs auth whoami` also names the kind of access token in use, and
  `rvs account list` adds a name column.
- A selected repository is shown as `repo:NAMESPACE/REPOSITORY`, including in
  publish confirmations and `--json` output.
- When Ravenstash no longer supports an API this release uses, every command,
  including sign-in refresh and package-tool wrappers, stops with a message to
  update `rvs` and exit status 1. `rvs auth logout`, `rvs profile delete`, and
  `rvs profile rename` still remove local credentials before they report it.
- Refreshing a sign-in waits and retries when Ravenstash is briefly busy and
  says how long to wait.

### Removed

- `rvs context current`, `rvs account current`, and `rvs art current`. Use
  `rvs status` or `rvs art status`.

Detailed release notes: [RVS 0.14.13](docs/releases/0.14.13.md).

## [0.14.12] - 2026-09-27

### Security

- `rvs` no longer reads a `.rvs.env` file from the current directory or its
  parents, so a checked-out project cannot redirect `rvs`. Besides
  `~/.rvs/profiles.env`, an env file is read only when `RVS_ENV_FILE` names it,
  and that file must belong to you and must not be writable by group or others.
- Endpoint settings from the environment or an env file only apply while a
  profile is being created. They never change the Ravenstash API or
  package-registry addresses of a saved profile, and `rvs` warns when one is
  ignored. Automation with `RVS_TOKEN` and no saved profile is unchanged.
- A stored sign-in is only sent to the Ravenstash API that issued it. If a
  profile's API no longer matches, commands stop and ask you to sign in again
  for that API.
- `rvs auth logout`, `rvs profile delete`, and `rvs profile rename` end the
  device session on the Ravenstash server as well as removing local
  credentials, and warn when the server could not be reached.
- Plain HTTP is accepted only for `localhost` and literal loopback addresses
  such as `127.0.0.1` and `::1`; other names, including `*.localhost`, need
  HTTPS.
- Evidence upload errors no longer print the temporary upload address.
- Text from Ravenstash is always shown literally; it can no longer change
  terminal formatting or inject control characters.
- `rvs mvn` gives the Ravenstash repository a random ID for each run, so a
  project file cannot claim the ID that receives the temporary credential.
- `rvs update` refuses a release-channel manifest that has expired or is older
  than one it has already accepted.

### Changed

- `rvs` follows the updated Ravenstash `v0` developer API for OCI tags,
  package-version files, native registry discovery, private mirrors, upstream
  sources, and package evidence. Earlier `rvs` releases cannot use these
  routes once Ravenstash adopts the update.
- `rvs art oci manifest list` shows each manifest's newest tags and total tag
  count. `rvs art oci tag list PATH --digest sha256:DIGEST` lists every tag of
  one manifest.
- `rvs art package show --version` reads every page of the version's files. With
  `--json`, the document also carries the version's `file_count`.

Detailed release notes: [RVS 0.14.12](docs/releases/0.14.12.md).

## [0.14.11] - 2026-09-26

### Removed

- `rvs art repo rename`, `rvs art repo delete`, `rvs art repo upstream add`,
  `update`, and `remove`, `rvs art mirror set-age`, `rvs art mirror delete`, and
  `rvs art package delete` are removed. These operations are managed in the
  Ravenstash web app only. Listing and showing repositories, upstreams, and
  mirrors, deleting single package versions and OCI content, and yanking or
  deprecating versions stay in `rvs`.

### Changed

- `rvs art package` commands use the repository chosen with `rvs art select`
  when `--target` is omitted, and need `--format` only when the repository has
  more than one package format. Yank, unyank, deprecate, and undeprecate no
  longer ask for a format. `package delete-version` resolves the repository
  before asking for confirmation and names it in the prompt.
- `rvs art package show` now shows the package summary with its newest 50
  versions, newest first, and says on stderr when more versions exist. Use
  `--limit N` (1–100) to show fewer or more, `--all-versions` to list every
  version, or `--version VERSION` to show one version with its files and every
  file digest. The versions table now has a published time and file count
  instead of per-version reasons and bandwidth; the separate artifacts table is
  replaced by `--version`. The summary adds status reason, latest stable
  version, last upload, and npm distribution tags. With `--json`, it prints one
  document with the `package` summary, the listed `versions`, and
  `versions_next_cursor` (null once every version is listed); `--version`
  prints one document whose files carry a `digests` object keyed by algorithm.
- Listings such as `rvs art repo list`, `rvs art package list`,
  `rvs art mirror list`, and `rvs account list` read every page from
  Ravenstash instead of only the first. Commands with `--limit` and `--cursor`
  (`rvs art oci ...` lists and `rvs art evidence list`) still return exactly one
  page.
- `rvs art oci tag create` sets the tag with the new tag route and reports
  whether the tag was created or already existed; with `--json` it prints the
  tag, digest, and `created`. OCI tag and manifest deletions print a
  confirmation instead of the former response object.
- Read commands retry when Ravenstash rate-limits them or is briefly
  unavailable, waiting as long as the server's `Retry-After` asks (up to 30
  seconds), and refresh the session if it expired meanwhile. Sign-in polling
  also backs off when rate-limited or briefly unavailable, without waiting past
  the sign-in deadline. Errors for longer waits say when to retry. API errors
  are shown as their code and message instead of a raw object.
- New formats, statuses, account types, and other values that `rvs` does not
  yet recognize are displayed as Ravenstash reports them instead of stopping the
  command. `rvs art select` refuses a target whose format or namespace realm it
  cannot store, `rvs account switch` accepts the shown `type:handle` of a new
  account type, and `rvs art evidence --wait` stops at an intent state it does
  not know.
- `rvs` requires the final Ravenstash `v0` developer API: temporary tokens use
  one native repository path, evidence uploads follow the typed upload
  instruction, and `rvs art evidence retire` uses the dedicated retire route.

Detailed release notes: [RVS 0.14.11](docs/releases/0.14.11.md).

## [0.14.10] - 2026-09-26

### Changed

- When `RVS_TOKEN` is set, a repository or format that Ravenstash reports as
  missing now includes a hint to check that the token covers that repository and
  format. Automation tokens can be limited to selected formats, and Ravenstash
  hides what a token does not cover. Private mirrors and formats that do not
  apply to the target get no hint.

Detailed release notes: [RVS 0.14.10](docs/releases/0.14.10.md).

## [0.14.9] - 2026-09-26

### Fixed

- `rvs update` on APT installations now checks the signed release channel, so it
  reports a new release even when the local APT package list is out of date.
  Previously it reported "You are up to date" until `sudo apt-get update` ran.
- `rvs update --apply` refreshes only the Ravenstash APT source before
  installing, so an unrelated broken or slow APT source no longer blocks an rvs
  update, and it stops with a clear message when APT still does not offer the
  signed release (for example because of a pin, hold, or mirror delay).

Detailed release notes: [RVS 0.14.9](docs/releases/0.14.9.md).

## [0.14.8] - 2026-09-26

### Changed

- `rvs` now uses the product-grouped Ravenstash developer API: sign-in and
  account resources live under `/v0/platform/` and repository, mirror, package,
  OCI, token, and evidence resources under `/v0/artifacts/`. This release
  requires the product-grouped service and does not work against a service that
  serves only the former routes. Once the service moves, releases 0.10 through
  0.14.7 stop working and report an "upgrade rvs" message.
- Native registry addresses are discovered from the Artifacts metadata endpoint
  after `rvs auth login` and after each session refresh. A failed discovery keeps
  the saved addresses and never fails the command; `rvs auth login` warns when it
  could not refresh them.
- `rvs art repo upstream update` and `remove` now take the source's `POSITION`
  (1–4) instead of a source ID, and `upstream list` shows position as its
  addressing column together with the source type and permanent ID.
- `rvs art token mint --access` now requests the `read`, `publish`, and `delete`
  grant operations; `--all-formats` covers every enabled lane, including OCI.
- `rvs art evidence list` lists intents of every package format in the
  repository and shows each intent's format; `--format` is optional.
- Machine-readable output that echoes API objects follows the new API field
  names: `rvs art evidence ... --json` intents use `ref`, `repository_ref`, and
  `package_name`; `rvs art oci ... --json` objects no longer carry `format`; and
  `rvs art repo upstream list --json` rows use `position`, `type`, `source`, and
  `source_ref` instead of `id`, with `type` values `repository` and
  `remote_cache` instead of `private` and `remote`.
- `rvs art token mint` now rejects a private-mirror token issued for another
  mirror or format.
- `rvs art mirror show`, `set-age`, and `delete` address a private mirror only by
  its `rc_...` permanent ID. Their `--account` options, and the `--format` option
  of `set-age` and `delete`, are now hidden and ignored for script compatibility.

### Removed

- `install.sh` no longer installs portable releases older than 0.14.7 through
  `RVS_INSTALL_VERSION`; earlier releases predate the rolling `v0` channel.

Detailed release notes: [RVS 0.14.8](docs/releases/0.14.8.md).

## [0.14.7] - 2026-09-25

### Added

- `install.sh` accepts `RVS_INSTALL_METHOD=portable` to force the authenticated
  portable archive on any supported Linux, including Debian-family CI runners,
  without configuring APT. `RVS_INSTALL_VERSION` selects an exact signed stable
  or candidate release on that path.
- `rvs art evidence stage`, `status`, and `sbom` stage package evidence such as
  CycloneDX SBOMs, report its processing status, and download analyzed SBOMs
  without changing native publishing.

### Changed

- `rvs art repo list` shows the effective access level (`Read`, `Publish`, or
  `Admin`) for each repository.
- User and organization account resources are now displayed unambiguously as
  `user:USERNAME` and `org:HANDLE`; both typed forms are accepted as selectors,
  while bare handles remain compatible.
- Pre-1 stable releases now share one rolling `v0` update channel across APT,
  portable archives, Nix, Homebrew, and WinGet.
- `rvs update --to 0.MINOR` now selects the latest signed stable patch in that
  minor line for one update without creating a persistent channel pin.
- The APT repository is now a single `v0` suite. Existing APT installations
  configured for the former `v0.14` suite must rerun the installer with
  `RVS_INSTALL_REPAIR=1`; earlier portable installations reinstall once.
- Signed APT metadata is refreshed daily instead of twice weekly.

Detailed release notes: [RVS 0.14.7](docs/releases/0.14.7.md).

## [0.14.6] - 2026-09-16

### Changed

- Stable releases now own installer validation, deployment, and channel
  promotion directly in `release.yml`, keeping each protected environment as a
  separate job while removing the unused standalone promotion workflow.

Detailed release notes: [RVS 0.14.6](docs/releases/0.14.6.md).

## [0.14.5] - 2026-09-16

### Changed

- Stable releases now stage and authenticate the exact GitHub draft while APT
  publishes, publish portable update policy alongside installer-promotion
  signing, and retain the existing public verification and recommendation
  barriers while shortening the release critical path.

Detailed release notes: [RVS 0.14.5](docs/releases/0.14.5.md).

## [0.14.4] - 2026-09-16

### Changed

- Repository selection now uses only the unified `rvs art select` target; the
  per-ecosystem repository-default commands and fallback configuration have
  been removed.
- Release and installer promotion workflows now accept only `main` release
  provenance and the current release workflow signer.

### Removed

- Removed the hidden `rvs account use` alias. Use `rvs account switch`.
- Removed maintenance-branch and historical release-signing compatibility.

Detailed release notes: [RVS 0.14.4](docs/releases/0.14.4.md).

## [0.14.3] - 2026-09-16

### Changed

- Top-level help groups package-tool wrappers by ecosystem and separates
  artifact management, account configuration, and setup commands into clearly
  labeled, alphabetically ordered sections.

Detailed release notes: [RVS 0.14.3](docs/releases/0.14.3.md).

[Unreleased]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.14.13...HEAD
[0.14.13]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.14.12...v0.14.13
[0.14.12]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.14.11...v0.14.12
[0.14.11]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.14.10...v0.14.11
[0.14.10]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.14.9...v0.14.10
[0.14.9]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.14.8...v0.14.9
[0.14.8]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.14.7...v0.14.8
[0.14.7]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.14.6...v0.14.7
[0.14.6]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.14.5...v0.14.6
[0.14.5]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.14.4...v0.14.5
[0.14.4]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.14.3...v0.14.4
[0.14.3]: https://github.com/rvstash/ravenstash-cli-alpha/releases/tag/v0.14.3
