# Ravenstash CLI quickstart

This guide takes you from sign-in to installing a private package.

## 1. Install and sign in

```bash
curl -fsSL https://ravenstash.com/install.sh | bash
rvs auth login
```

The login command opens Ravenstash in your browser. Return to the terminal when
the browser confirms that sign-in is complete.

## 2. Choose a personal account or organization

List the accounts you can use:

```bash
rvs account list
```

Choose one by its public name:

```bash
rvs account use Avery
rvs account use AcmeHQ
```

Use your Ravenstash username for your personal account. Use the public handle
shown on an organization's Ravenstash page for an organization. You only need
to run one of these commands.

## 3. Choose a repository

```bash
rvs art repo list
rvs art select platform/packages
```

The first name is the namespace and the second is the repository. Your current
choice is remembered for the selected account and profile.

Check it at any time:

```bash
rvs context current
```

## 4. Install a package

Use the command for your package format:

```bash
rvs pip install internal-sdk
rvs npm install @acme/design-system
rvs mvn verify
```

`rvs` gives the package tool temporary access for that command. It does not add
a Ravenstash token to the project's package settings.

## Use a private mirror

Choose a Ravenstash-provided mirror when you need public packages:

```bash
rvs art mirror create pypiorg --select
rvs pip install requests
```

Use `npmjs` for npm or `maven-central` for Maven. A mirror is read-only, so
select a private repository again before publishing.

## Publish a package

Select the destination first:

```bash
rvs art select platform/packages
rvs twine upload dist/*
```

You can also publish with `rvs npm publish` or `rvs mvn deploy`. Ravenstash shows
the destination and asks for confirmation before uploading.

In a protected automation job, add `--rvs-yes` before the wrapped tool's normal
arguments:

```bash
rvs npm --rvs-yes publish
```

## Use another profile

Profiles are useful when one computer connects to more than one Ravenstash
environment:

```bash
rvs auth login --profile work
rvs profile use work
rvs profile current
```

## Troubleshooting

Show the current choices:

```bash
rvs auth status
rvs account current
rvs art current
rvs context current
```

If no repository is selected, choose one with `rvs art select
NAMESPACE/REPOSITORY`. If a name is unclear, use `rvs art repo list` and copy the
namespace and repository names shown there.

For more help, see the [public CLI documentation](https://docs.ravenstash.com/cli/overview/).
