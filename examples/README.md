# rvs Examples

These projects are small package examples for trying the current alpha `rvs`
surface. They are ordinary Python, npm, and Maven projects; use native tooling
for local build/test work, and use `rvs art` when interacting with a private
Ravenstash package repository.

```text
examples/
├── python/   PyPI project
├── npm/      npm project
└── java/     Maven project
```

## Runtime Setup

```bash
rvs runtime install python 3.12
rvs runtime install node 22
rvs runtime install java 21
rvs runtime setup-shell
```

Inside a project, pin the runtime:

```bash
rvs runtime use python 3.12
rvs runtime use node 22
rvs runtime use java 21
```

## Private Package Repository Setup

```bash
rvs auth login
rvs art repo list
rvs art repo create my-python-packages --ecosystem pypi --default
rvs art repo create my-node-packages --ecosystem npm --default
rvs art repo create my-java-packages --ecosystem maven --default
```

`rvs art` expects package repository names, such as `my-python-packages`.
After a repository is set as the default for its ecosystem, the `--repo` flag can be
omitted for that ecosystem.

## Package Helpers

```bash
rvs art pypi index-url
rvs art pypi publish dist/
rvs art pypi install my-private-package

rvs art npm registry-url
rvs art npm publish .
rvs art npm install my-private-package

rvs art maven repo-url
rvs art maven deploy target/app.jar --group com.example --artifact app --version 0.1.0
rvs art maven install com.example:app:0.1.0
```
