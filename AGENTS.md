# AGENTS.md

Operational guidance for the `rvs` CLI package.

## What this repository is

- Ravenstash developer CLI for auth, local runtime management, package repositories, and future developer-product areas.
- The CLI manages Ravenstash credentials, including refresh-backed expiring
  device-login credentials, and delegates install flows to native toolchains
  where appropriate.
- CLI code lives under `rvs/`, organized by command area: `auth/`, `runtime/`, `pkg/`, `repo/`, and `ci/`.

## Working rules

- Keep user credentials in the established config/keyring flow: access tokens
  and profile-scoped device refresh tokens live in keyring, while profile
  metadata lives in `~/.rvs/config.toml`.
- Preserve native-toolchain delegation for install flows unless the task explicitly changes that contract.
- Keep registry-specific protocol logic in `rvs/pkg/registries/{pypi,npm,maven}.py`.
- Keep the DevAPI control plane, package download, and package upload URLs
  distinct in profile metadata; never derive registry routes from the DevAPI
  URL. The CLI must never call Central directly.
- Keep command modules thin and route shared behavior through common helpers.
- Do not hardcode local, dev, or staging Ravenstash endpoints. Support them
  through user config, process environment variables, or ignored env files such
  as `.rvs.env` and `~/.rvs/profiles.env`.
- Keep packaging, APT publication policy, the installer Worker, and release
  workflows reviewable in this repository. Secret values belong only in the
  documented GitHub environments and originate in production Infisical.
- Never add destructive APT reset behavior. Published versions and repository
  objects are append-only; corrections use a new patch version.
- Keep real-environment integration tests and their tokens in the separate
  private integration repository. It must not receive signing, storage-write,
  or installer-deployment credentials.

## Verification

Run from `packages/rvs/` after code changes:

```bash
.venv/bin/pytest
.venv/bin/ruff check rvs tests
.venv/bin/pyright
```
