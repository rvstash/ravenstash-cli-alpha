# rvs-demo-npm

Minimal Node.js project for testing the alpha `rvs` package repository commands.

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
rvs art repo create my-node-packages --ecosystem npm --default
rvs art npm registry-url
rvs art npm npmrc
rvs art npm publish .
rvs art package list --repo <repo-name>
```

To install from a private Ravenstash npm repository:

```bash
rvs art npm install rvs-demo-npm --repo <repo-name>
```
