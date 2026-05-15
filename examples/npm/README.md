# rvn-demo-npm

Minimal Node.js project for hands-on testing of `rvn` CLI commands.

## What's in here

| File | Purpose |
|------|---------|
| `package.json` | Real npm project: axios, lodash, chalk, zod, dotenv |
| `src/index.js` | CLI that hits the public npm registry API |
| `src/utils.js` | Formatting helpers using lodash + chalk |

## Try it — public registry, no account needed

```bash
# 1. Pin Node.js runtime
rvn node pin 20              # falls back to nodejs.org download if fnm/volta not found

# 2. Install dependencies from public npm
rvn npm install              # runs: npm install

# 3. Inspect the project
rvn npm ls                   # npm ls
rvn npm view lodash          # npm view lodash
rvn npm view axios versions  # list all axios versions
rvn npm outdated             # check for outdated deps

# 4. Run the demo app
node src/index.js info lodash
node src/index.js info axios
node src/index.js versions chalk --limit 5

# 5. Linting / formatting via rvnx (no global install)
rvnx --npm prettier src/     # format with prettier (via npx)
rvnx --npm eslint src/       # lint with eslint (via npx)
```

## Try it — private registry (needs rvn auth login)

```bash
# Login first
rvn auth login --api-url https://api.ravenstash.com

# Show the .npmrc snippet to authenticate against your private repo
rvn npm npmrc --repo my-npm-repo

# Show the registry URL
rvn npm registry-url --repo my-npm-repo

# Publish to your private npm repo
rvn npm publish --repo my-npm-repo

# Bump version
rvn npm bump patch           # npm version patch → 0.1.0 → 0.1.1

# Manage dist-tags
rvn npm dist-tag ls  --repo my-npm-repo --name rvn-demo-npm
rvn npm dist-tag add --repo my-npm-repo --name rvn-demo-npm --version 0.2.0 --tag beta
rvn npm dist-tag rm  --repo my-npm-repo --name rvn-demo-npm --tag beta

# Snapshot publish (publishes with --tag snapshot)
rvn npm snapshot publish --repo my-npm-repo
rvn npm snapshot ls     --repo my-npm-repo --name rvn-demo-npm

# Deprecate / yank a version
rvn npm deprecate --repo my-npm-repo --name rvn-demo-npm --version 0.1.0 \
    --message "Use 0.1.1 instead"
rvn npm yank --repo my-npm-repo --name rvn-demo-npm --version 0.1.0
```
