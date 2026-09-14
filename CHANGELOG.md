# Changelog

All notable user-facing changes to `rvs` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Signed GitHub release candidates installable on Debian-family systems with
  `rvs update --candidate X.Y.ZrcN [--apply]`.
- Public governance, contribution, security, support, issue, and pull-request
  guidance.

### Changed

- Normal development now targets `main`; supported maintenance lines use
  `release/vMAJOR.MINOR` branches and matching APT suites.
- CI runs for ready pull requests and protected-branch commits, not ordinary
  feature-branch pushes.
- Pull requests use rebase merges exclusively.
- The project and its release artifacts are now licensed under Apache-2.0.
- Runtime dependencies pin `cryptography` and `idna` to their reviewed exact
  versions.

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

[Unreleased]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.13.4...HEAD
[0.13.4]: https://github.com/rvstash/ravenstash-cli-alpha/releases/tag/v0.13.4
