# rvn-demo-npm

Minimal Node.js project for testing the alpha `rvn` package repository commands.

## Local Work

```bash
cd examples/npm
rvn runtime use node 22
npm install

node src/index.js info lodash
node src/index.js info axios
node src/index.js versions chalk --limit 5
```

## Ravenstash Package Repository

```bash
rvn auth login
rvn pkg repo create my-node-packages --kind npm --default
rvn pkg npm registry-url
rvn pkg npm npmrc
rvn pkg npm publish .
rvn pkg package list --repo <repository-id>
```

To install from a private Ravenstash npm repository:

```bash
rvn pkg npm install rvn-demo-npm --repo <repository-id>
```
