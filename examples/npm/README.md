# rvs-demo-npm

Minimal Node.js project for testing the `rvs` package repository commands.

## Local Work

```bash
cd examples/npm
rvs runtime use node 22
npm install

node src/index.js info lodash
node src/index.js info axios
node src/index.js versions chalk --limit 5
```

## Ravenstash Package Repository

```bash
rvs auth login
rvs art repo create <namespace>/my-node-packages --format npm
rvs art select <namespace>/my-node-packages
rvs art endpoint --format npm
rvs art native config npm
rvs npm publish
rvs art package list
```

To install from a private Ravenstash npm repository:

```bash
rvs npm --rvs-target <namespace/repository> install rvs-demo-npm
```

## Distribution tags

Publish a prerelease under its own tag, install it by tag, and manage tags with
npm's own commands; `rvs` sends reads and changes to the right address:

```bash
rvs npm publish --tag beta
rvs npm install rvs-demo-npm@beta
rvs npm dist-tag ls rvs-demo-npm
rvs npm dist-tag add rvs-demo-npm@1.0.0 latest
rvs npm dist-tag rm rvs-demo-npm beta
```

Pointing `latest` at another version and removing a tag ask for confirmation;
pass `--rvs-yes` in automation. The same changes are available without npm:

```bash
rvs art package tag list rvs-demo-npm
rvs art package tag set rvs-demo-npm latest 1.0.0
rvs art package tag delete rvs-demo-npm beta
```
