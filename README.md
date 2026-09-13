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

The currently published alpha installer supports Linux amd64. Native Linux
arm64, Alpine, macOS, Windows, Nix, and WSL2 artifacts are gated on the first
public release certification described in the compatibility policy.

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
rvs art mirror create pypiorg --select
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

## Native setup and manual tokens

Print instructions without changing files or creating credentials:

```bash
rvs art native config pip
rvs art native config oras
rvs art endpoint --format npm
rvs art reference backend:latest --format oci
```

For tools outside the wrappers, `rvs art token mint --format oci
--access publish` creates one temporary credential for both content types in the selected
repository. Native logins may share a host credential store; the templates use
separate temporary OCI configs. A logout against a shared store can affect other tools.

`rvs update --to SERIES` previews a newer release series. Only `--apply` installs it.

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

Multi-format options accept comma-separated values, repeated flags, or both:

```bash
rvs art repo create packages --format pypi,npm,maven,oci
rvs art token mint --target platform/packages -f container -f helm
```

Whitespace is trimmed and duplicates are removed. Empty or unknown formats fail
before any mutation. Commands requiring one format still accept only one.


OCI is one repository format containing container images and Helm charts. Manage
its graph without launching a native tool:

```bash
rvs art oci list --content-type helm_chart --target platform/packages
rvs art oci manifest list charts/api
rvs art oci manifest show charts/api@sha256:YOUR_DIGEST
rvs art oci tag list charts/api
```

Lists expose `--limit` and `--cursor`; root `--json` retains pagination metadata.
Use `rvs docker`, `rvs helm`, or `rvs oras` to transfer native content. ORAS needs
no Ravenstash format flag. Wrapper credentials and logout changes stay in temporary
configuration, including independent ORAS copy source/destination configs.
