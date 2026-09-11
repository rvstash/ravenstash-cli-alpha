# rvs — the Ravenstash CLI

`rvs` lets you sign in to Ravenstash, choose a personal account or organization,
and use private package repositories from the command line.

It works with PyPI, npm, Maven, Container, and Helm repositories. It can also
run pip, uv, Twine, npm, Maven, Docker, Helm, and ORAS with temporary Ravenstash
access, so credentials do not need to be saved in project files.

## Install

```bash
curl -fsSL https://ravenstash.com/install.sh | bash
rvs --version
```

For supported systems and upgrade instructions, see the
[CLI overview](https://docs.ravenstash.com/cli/overview/).

## Get started

Sign in, choose an account, and choose a repository:

```bash
rvs auth login
rvs account list
rvs account use AcmeHQ
rvs art select platform/packages
```

Use your Ravenstash username for a personal account. Use an organization's
public handle for an organization. Names are matched without regard to letter
case.

Then run the package tool you already use:

```bash
rvs pip install internal-sdk
rvs uv sync
rvs npm ci
rvs mvn verify
```

`platform/packages` means the `packages` repository in the `platform`
namespace. Run `rvs art repo list` to see the repositories available to the
selected account.

## Private mirrors

A private mirror gives your account a read-only view of a public or custom
package source:

```bash
rvs art mirror add pypiorg --select
rvs pip install requests
```

You can switch back to a private repository at any time:

```bash
rvs art select platform/packages
```

## Publish safely

Publishing commands show the account, repository, and files before asking for
confirmation:

```bash
rvs twine upload dist/*
rvs npm publish
rvs mvn deploy
```

In a protected automation job, use `--rvs-yes` with these wrapped tools. The
built-in `rvs art` publishing commands use `--yes` instead.

## Profiles and runtimes

Profiles let one computer remember separate Ravenstash sign-ins or settings:

```bash
rvs auth login --profile work
rvs profile use work
rvs context current
```

The CLI can also install and select Python, Node.js, and Java versions:

```bash
rvs runtime install python 3.14
rvs runtime use python 3.14
rvs runtime list
```

## Documentation

- [Quickstart](docs/quickstart.md)
- [Command reference](docs/command-reference.md)
- [Public Ravenstash documentation](https://docs.ravenstash.com/cli/overview/)

## Contributing

Run the repository checks from this directory:

```bash
.venv/bin/pytest
.venv/bin/ruff check rvs tests
.venv/bin/pyright
```

`rvs` is licensed under the [MIT License](LICENSE).
