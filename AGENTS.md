# AGENTS.md

Operational guidance for the `rvn` CLI package.

## What this repository is

- Universal Ravenstash package-manager CLI for publishing and consuming PyPI, npm, and Maven packages.
- The CLI manages Ravenstash credentials, including refresh-backed expiring
  device-login credentials, and delegates install flows to native toolchains
  where appropriate.
- CLI code lives under `rvn/`, with registry-specific behavior under `rvn/registries/` and command wiring under `rvn/commands/`.

## Working rules

- Keep user credentials in the established config/keyring flow: access tokens
  and profile-scoped device refresh tokens live in keyring, while profile
  metadata lives in `~/.rvn/config.toml`.
- Preserve native-toolchain delegation for install flows unless the task explicitly changes that contract.
- Keep registry-specific protocol logic in `rvn/registries/{pypi,npm,maven}.py`.
- Keep command modules thin and route shared behavior through common helpers.
- Do not assume public Ravenstash endpoints are finalized; support local/dev profiles through configuration.

## Verification

Run from `packages/rvn/` after code changes:

```bash
uv sync
uv run pytest
uv run ruff check rvn tests
```
