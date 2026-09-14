# AGENTS.md

This file is the complete operating guide for automated contributors to the
public `rvs` repository. Do not rely on instructions from a parent checkout or
from private Ravenstash repositories.

## Repository scope

`rvs` is the Ravenstash command-line client. Application code lives in `rvs/`,
tests in `tests/`, user documentation in `docs/`, examples in `examples/`, and
release/install tooling in `packaging/` and `.github/workflows/`.

Keep user identity, the local profile, the acting account, and the selected
artifact target distinct. Keep secrets in the established credential stores;
non-secret profile metadata belongs in `~/.rvs/config.toml`. Native install and
publish flows should continue to delegate to their native tools. Keep the
control-plane URL separate from package download and upload URLs.

## Contribution workflow

- Never commit or push directly to `main` or `release/vMAJOR.MINOR`. This rule
  applies even though repository administrators retain a human-only emergency
  bypass.
- Create a short-lived branch, open a pull request, and use a rebase merge.
  Merge commits and squash merges are not part of this repository's workflow.
- Target `main` for normal development. Target the applicable
  `release/vMAJOR.MINOR` branch only for a supported-line backport or hotfix.
- Keep commits reviewable and self-contained. Rebase the branch when it is
  behind its target; do not merge the target branch into it.
- Preserve unrelated changes in a dirty worktree.
- Do not commit, push, open or merge a pull request, tag, publish, release,
  deploy, or otherwise mutate an external environment unless the user
  explicitly requests that action.

## Implementation rules

- Keep command modules thin and route shared behavior through common helpers.
- Keep registry-specific protocol behavior in the applicable `rvs/artifacts/`
  or `rvs/native/` module; do not mix it into unrelated command groups.
- Do not hardcode development or staging endpoints. Support alternate
  environments through user configuration or process environment variables.
- Never add destructive APT reset behavior. Published versions and repository
  objects are append-only; corrections receive a new patch version.
- Release candidates use PEP 440 `X.Y.ZrcN` versions and GitHub prereleases.
  They must not be added to stable APT suites.
- A release bump is a dedicated final commit containing the version, matching
  lockfile and installer updates, and release notes.

## Verification

Run from the repository root:

```bash
.venv/bin/pytest
.venv/bin/ruff format --check rvs tests packaging/repository packaging/scripts
.venv/bin/ruff check rvs tests packaging/repository packaging/scripts
.venv/bin/pyright
```

For workflow or packaging changes, also run actionlint, shellcheck, the
`packaging/repository` unit tests, and the installer Worker tests when those
tools are available. Report files changed, checks run and their results, and
any relevant check that could not be run.
