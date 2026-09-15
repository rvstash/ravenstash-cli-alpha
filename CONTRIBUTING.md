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
4. Resolve review conversations and wait for the aggregate `CI gate`.
5. After approval and successful required gates, a maintainer uses one of the
   two allowed linear landing modes: one verified squash commit, or a local
   `git merge --ff-only <topic-branch>` followed by a target-branch push.

Fast-forwarding preserves the reviewed commit object IDs and signatures. A
squash intentionally replaces the PR commits with one new commit, which must be
signed or otherwise verified under the repository's protection rules. Do not
use GitHub's **Rebase and merge**, create a merge commit, or force-push a
protected branch. If the target advanced, either squash or have the contributor
update and re-sign the branch before a fast-forward landing.

Pull requests are preferred because they provide review and required CI. While
this is the alpha repository, maintainers and automated contributors may push a
direct linear update to `main` or `release/*` when explicitly authorized. The
same required checks must pass for the exact resulting protected-branch commit.

## When CI runs

- A push to a feature branch with no pull request runs no repository CI.
- Opening, reopening, updating, or marking ready a non-draft pull request to
  `main` or `release/*` starts one CI run. A selector fans out only the checks
  affected by the changed paths; independent jobs run in parallel and converge
  on the stable `CI gate`. A new commit cancels the superseded run.
- A squash or fast-forward push to `main` or `release/*` reruns that path-aware
  CI for the exact protected-branch commit. It does not build every release
  target and never publishes anything. Release automation accepts only an exact
  SHA that passed the aggregate gate.
- A manual CI dispatch deliberately runs every check. Use it when a path-limited
  run is insufficient for investigation; it is not a release operation.
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
