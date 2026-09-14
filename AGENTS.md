# AGENTS.md

Operational guidance for the `rvs` CLI package.

## Agent workflow

- For cross-repository, product-policy, release, or production work, first read
  `../../AGENTS.md` and the authoritative documents it identifies.
- Reviews and investigations are read-only. For implementation, complete the
  authorized local change and run the smallest relevant verification.
- Never commit or push directly to `dev`. Create a short-lived branch and use a
  pull request; treat authorization to commit or push as authorization for that
  branch workflow unless the human explicitly directs an emergency bypass.
- Do not commit, push, release, publish, or mutate a real environment unless the
  user explicitly requests it. Report changed files and verification results.

## What this repository is

- Ravenstash developer CLI for authentication, named local profiles, acting-account
  and artifact-target context, local runtime management, artifact repositories, and
  future developer-product areas.
- The CLI manages Ravenstash credentials, including refresh-backed expiring
  device-login credentials, and delegates install flows to native toolchains
  where appropriate.
- CLI code lives under `rvs/`, organized by command area: `auth/`, `account/`,
  `context/`, `runtime/`, `artifacts/`, `native/`, and `oci/`.

## Working rules

- Keep the authenticated user, named local profile, acting account, and artifact
  target distinct. A profile is local CLI configuration, not the Ravenstash user.
- Keep user credentials in the established credential-store flow: access tokens
  and profile-scoped device refresh tokens live in the selected keyring, `pass`,
  vault, or explicitly acknowledged plaintext store, while non-secret profile,
  account, and target metadata lives in `~/.rvs/config.toml`.
- Preserve native-toolchain delegation for install flows unless the task explicitly changes that contract.
- Keep registry-specific protocol logic in `rvs/artifacts/registries/{pypi,npm,maven}.py`.
- Keep the DevAPI control plane, package download, and package upload URLs
  distinct in profile metadata; never derive registry routes from the DevAPI
  URL. The CLI must never call Central directly.
- Internal environment redirection may use one profile-scoped DevAPI URL and,
  for DNS families shaped as `{service}.{domain}`, one repository-domain suffix.
  When that suffix is configured, derive every PyPI, npm, Maven, mirror, push,
  and OCI host from it; otherwise retain the exact endpoints discovered from
  DevAPI. A suffix equal to or ending in `localhost` uses the literal
  `localhost` host and distinguishes services through the discovered ports and
  paths. Do not add per-format environment overrides.
- Keep command modules thin and route shared behavior through common helpers.
- Do not hardcode local, dev, or staging Ravenstash endpoints. Support them
  through user config, process environment variables, or ignored env files such
  as `.rvs.env` and `~/.rvs/profiles.env`.
- Keep packaging, APT publication policy, the installer Worker, and release
  workflows reviewable in this repository. Secret values belong only in the
  documented GitHub environments and originate in production Infisical.
- Never add destructive APT reset behavior. Published versions and repository
  objects are append-only; corrections use a new patch version.
- Keep real-environment integration tests and their tokens in the Ravenstash QA
  repository. It must not receive signing, storage-write,
  or installer-deployment credentials.

## Verification

Run from `packages/rvs/` after code changes:

```bash
.venv/bin/pytest
.venv/bin/ruff check rvs tests
.venv/bin/pyright
```
