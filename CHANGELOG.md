# Changelog

All notable user-facing changes to `rvs` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Pre-1 stable releases now share one rolling `v0` update channel across APT,
  portable archives, Nix, Homebrew, and WinGet.
- `rvs update --to 0.MINOR` now selects the latest signed stable patch in that
  minor line for one update without creating a persistent channel pin.

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

[Unreleased]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.14.6...HEAD
[0.14.6]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.14.5...v0.14.6
[0.14.5]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.14.4...v0.14.5
[0.14.4]: https://github.com/rvstash/ravenstash-cli-alpha/compare/v0.14.3...v0.14.4
[0.14.3]: https://github.com/rvstash/ravenstash-cli-alpha/releases/tag/v0.14.3
