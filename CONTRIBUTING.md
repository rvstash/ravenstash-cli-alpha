# Contributing to rvs

Thank you for helping improve the Ravenstash CLI.

Unless explicitly stated otherwise, contributions intentionally submitted for
inclusion in this repository are licensed under the Apache License 2.0, the same
license as the project, without additional terms or conditions.

## Branches and pull requests

Normal development targets `main`. A maintained compatibility line has a
`release/vMAJOR.MINOR` branch, such as `release/v0.13` or `release/v1.1`.
Maintenance branches are created only while that line is supported; they are
not created for every APT package or patch release.

1. Update the target branch and create a short-lived branch such as
   `feat/<topic>`, `fix/<topic>`, `ci/<topic>`, or `docs/<topic>`.
2. Make focused commits and open a pull request against `main`, or against the
   relevant maintenance branch for an intentional backport.
3. Mark the pull request ready when it should enter CI. Draft pull requests do
   not run the expensive suites.
4. Resolve review conversations and wait for `Source CI gate`,
   `Platform CI gate`, and `Release policy gate`.
5. Rebase onto the target when required, then use GitHub's **Rebase and merge**.

Merge commits and squash merges are disabled. Do not merge the target branch
into a feature branch. GitHub deletes merged feature branches automatically.

Direct pushes to `main` and `release/*` are forbidden by project policy.
Administrators retain a bypass solely for time-critical emergencies. A human
who uses it must document why, run the same checks, and follow up with a pull
request or incident record. Automated contributors must never use that bypass.

## When CI runs

- A push to a feature branch with no pull request runs no repository CI.
- Opening, reopening, updating, or marking ready a non-draft pull request to
  `main` or `release/*` runs Source CI, Platform CI, and Release policy in
  parallel. A new commit cancels superseded runs for that pull request.
- A merge or emergency push to `main` or `release/*` reruns those gates for the
  exact protected-branch commit. Release automation accepts only an exact SHA
  that passed all required gates.
- Platform certification is manual and scheduled. Release candidates and
  stable releases require a successful certification run for their exact SHA.

This means ordinary branch experimentation is quiet, while every commit that
could merge or release is tested.

## Local checks

```bash
.venv/bin/pytest
.venv/bin/ruff format --check rvs tests packaging/repository packaging/scripts
.venv/bin/ruff check rvs tests packaging/repository packaging/scripts
.venv/bin/pyright
```

Workflow or packaging changes must also pass actionlint, shellcheck, repository
policy tests, and installer Worker tests.

## Releases and backports

Every compatibility line uses the same identifier in two different systems:
Git branch `release/v1.1` and APT suite `v1.1`. The branch contains source; the
APT suite contains immutable signed packages. A patch tag such as `v1.1.3` does
not receive its own branch.

Prepare a version on the branch that owns that line. The final version commit
contains only the project version, lockfile, installer constants, and release
notes. See [RELEASING.md](RELEASING.md) for stable and candidate procedures.

## Community

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report vulnerabilities
through the private process in [SECURITY.md](SECURITY.md), not a public issue.
Use [SUPPORT.md](SUPPORT.md) to choose between support and an issue.
