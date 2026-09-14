# Contributing to rvs

The `dev` branch is the protected integration and release branch. Do not commit
or push directly to it. Every source, documentation, CI, and version change uses
a short-lived branch and a pull request targeting `dev`.

## Change workflow

1. Update local `dev`, then create a branch such as `feat/<topic>`, `fix/<topic>`,
   `ci/<topic>`, `docs/<topic>`, or `release/vX.Y.Z`.
2. Commit related work on that branch and push it to GitHub.
3. Open a pull request targeting `dev`. Opening or updating the pull request runs
   Source CI, Platform CI, and Release policy in parallel.
4. Merge only when `Source CI gate`, `Platform CI gate`, and
   `Release policy gate` pass and all review conversations are resolved.
5. Use squash merge. GitHub deletes the merged branch automatically. Update local
   `dev` before starting the next change.

A push to a feature branch does not run the full test suite by itself; the pull
request is the CI boundary. Additional commits update the same pull request and
cancel superseded runs for that pull-request ref.

After merge, all three workflows run again against the new `dev` commit. This is
intentional: a squash merge has a different commit identity from the pull-request
head, and releases require successful checks for the exact `dev` SHA.

## Local checks

Run the repository checks before pushing:

```bash
.venv/bin/pytest
.venv/bin/ruff format --check rvs tests packaging/repository
.venv/bin/ruff check rvs tests packaging/repository
.venv/bin/pyright
```

Changes to GitHub Actions or packaging policy must also pass the checks in
`release-policy-ci.yml`, including actionlint, shellcheck, the repository policy
tests, and the installer Worker tests.

## Releases

A release starts with a dedicated `release/vX.Y.Z` pull request. Its final commit
contains only the version change, matching lockfile update, generated installer
versions, and release notes.

After that pull request is squash-merged and the exact merged `dev` SHA passes all
required CI and platform certification, manually dispatch `release.yml` with that
SHA, version, and release series. The workflow creates the immutable Git tag and
GitHub release; do not create the tag by hand. Installer promotion and production
smoke tests remain separate, explicitly authorized operations.

Hotfixes follow the same pull-request path. Any emergency bypass is a deliberate
human action and must be documented; it is not the normal release process.
