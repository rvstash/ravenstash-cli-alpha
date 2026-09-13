# rvs Examples

These projects are small package examples for trying the current alpha `rvs`
surface. They are ordinary Python, npm, and Maven projects; `rvs` runs their
native tools with temporary access to a selected Ravenstash repository.

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
rvs art repo create my-python-packages --format pypi --default
rvs art repo create my-node-packages --format npm --default
rvs art repo create my-java-packages --format maven --default
```

`rvs art` expects package repository names, such as `my-python-packages`.
After a repository is set as the default for its ecosystem, the `--target` flag can be
omitted for that ecosystem.

## Native Package Tools

```bash
rvs art endpoint --format pypi
rvs twine upload dist/*
rvs pip install my-private-package

rvs art endpoint --format npm
rvs npm publish
rvs npm install my-private-package

rvs art endpoint --format maven
rvs mvn deploy
rvs mvn dependency:get -Dartifact=com.example:app:0.1.0
```
