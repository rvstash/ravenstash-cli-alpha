# AGENTS.md

Operational guidance for the `rvn` CLI package.

## What this repository is

- Ravenstash developer CLI for auth, local runtime management, package repositories, and future developer-product areas.
- The CLI manages Ravenstash credentials, including refresh-backed expiring
  device-login credentials, and delegates install flows to native toolchains
  where appropriate.
- CLI code lives under `rvn/`, organized by command area: `auth/`, `runtime/`, `pkg/`, `repo/`, and `ci/`.

## Working rules

- Keep user credentials in the established config/keyring flow: access tokens
  and profile-scoped device refresh tokens live in keyring, while profile
  metadata lives in `~/.rvn/config.toml`.
- Preserve native-toolchain delegation for install flows unless the task explicitly changes that contract.
- Keep registry-specific protocol logic in `rvn/pkg/registries/{pypi,npm,maven}.py`.
- Keep DevAPI authentication, package control API, package download, and package
  upload URLs distinct in profile metadata; never derive registry routes from
  the DevAPI URL.
- Keep command modules thin and route shared behavior through common helpers.
- Do not hardcode local, dev, or staging Ravenstash endpoints. Support them
  through user config, process environment variables, or ignored env files such
  as `.rvn.env` and `~/.rvn/profiles.env`.

## Verification

Run from `packages/rvn/` after code changes:

```bash
.venv/bin/pytest
.venv/bin/ruff check rvn tests
```
