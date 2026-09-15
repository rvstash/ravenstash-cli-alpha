# Changelog

All notable user-facing changes to `rvs` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.13.7] - 2026-09-15

### Changed

- `rvs art endpoint` now shows both read and publish endpoints for repositories;
  `--access` retains single-value output for scripts.

Detailed release notes: [RVS 0.13.7](docs/releases/0.13.7.md).

## [0.13.6] - 2026-09-15

### Changed

- Runtime, development, and release dependencies are upgraded and exactly
  pinned; the HTTP client is migrated from HTTPX to HTTPX2.
- Nix builds now consume the committed `uv.lock`, keeping their Python
  dependency graph aligned with portable and native CI builds.
### Fixed

- Candidate installation now reads Debian package identity with an explicit
  machine-readable format before comparing its name, version, and architecture.

Detailed release notes: [RVS 0.13.6](docs/releases/0.13.6.md).

## [0.13.5] - 2026-09-15

### Added

- Signed GitHub release candidates installable on Debian-family systems with
  `rvs update --candidate X.Y.ZrcN [--apply]`.
- Public governance, contribution, security, support, issue, and pull-request
  guidance.
- Interactive `rvs account switch` selection for personal accounts and
  organizations.
- Expiring, unsigned test builds for installing an exact commit without
  publishing a release candidate.

### Changed

- Normal development now targets `main`; supported maintenance lines use
  `release/vMAJOR.MINOR` branches and matching APT suites.
- Ready pull requests and protected-branch commits use one path-aware CI run
  with parallel affected checks and one aggregate gate; ordinary feature-branch
  pushes remain quiet.
- Pull requests use one verified squash commit or a local fast-forward landing;
  merge commits and GitHub rebase merges are excluded.
- The project and its release artifacts are now licensed under Apache-2.0.
- Runtime dependencies pin `cryptography` and `idna` to their reviewed exact
  versions.
- `rvs account switch HANDLE` is now the canonical direct account-selection
  command; the former `account use` form remains as a hidden deprecated alias.
- Account selection and listings use public handles rather than mutable display
  names.

### Fixed

- Invalid or unsupported local configuration now produces a concise recovery
  message instead of a Python traceback.
- Runtime SBOM generation no longer emits the project as an unknown dependency.
- Portable and Debian release artifacts now include the project license,
  notice, and bundled runtime dependency license metadata.

## [0.13.4] - 2026-09-14

### Changed

- Unified release validation, eight parallel platform builds, assembly,
  signing, APT publication, verification, and GitHub publication in one visible
  workflow run.
- Gave top-level Actions runs distinct purpose-first names.
- Clarified the unified OCI repository model for container and Helm content.

Detailed release notes: [RVS 0.13.4](docs/releases/0.13.4.md).

## Earlier releases

Detailed notes for every earlier release are in [docs/releases](docs/releases/).

[Unreleased]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.13.7...HEAD
[0.13.7]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.13.6...v0.13.7
[0.13.6]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.13.5...v0.13.6
[0.13.5]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.13.4...v0.13.5
[0.13.4]: https://github.com/rvstash/ravenstash-cli-alpha/releases/tag/v0.13.4
