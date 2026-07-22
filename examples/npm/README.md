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
rvs pkg repo create my-node-packages --kind npm --default
rvs pkg npm registry-url
rvs pkg npm npmrc
rvs pkg npm publish .
rvs pkg package list --repo <repository-id>
```

To install from a private Ravenstash npm repository:

```bash
rvs pkg npm install rvs-demo-npm --repo <repository-id>
```
