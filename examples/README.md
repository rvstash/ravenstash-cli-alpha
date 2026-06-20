# rvn Examples

These projects are small package examples for trying the current alpha `rvn`
surface. They are ordinary Python, npm, and Maven projects; use native tooling
for local build/test work, and use `rvn pkg` when interacting with a private
Ravenstash package repository.

```text
examples/
├── python/   PyPI project
├── npm/      npm project
└── java/     Maven project
```

## Runtime Setup

```bash
rvn runtime install python 3.12
rvn runtime install node 22
rvn runtime install java 21
rvn runtime setup-shell
```

Inside a project, pin the runtime:

```bash
rvn runtime use python 3.12
rvn runtime use node 22
rvn runtime use java 21
```

## Private Package Repository Setup

```bash
rvn auth login
rvn pkg repo list
rvn pkg repo create my-python-packages --kind pypi --default
rvn pkg repo create my-node-packages --kind npm --default
rvn pkg repo create my-java-packages --kind maven --default
```

`rvn pkg` expects Ravenstash repository public IDs. After a repository is set as
the default for its kind, the `--repo` flag can be omitted for that kind.

## Package Helpers

```bash
rvn pkg pypi index-url
rvn pkg pypi publish dist/
rvn pkg pypi install my-private-package

rvn pkg npm registry-url
rvn pkg npm publish .
rvn pkg npm install my-private-package

rvn pkg maven repo-url
rvn pkg maven deploy target/app.jar --group com.example --artifact app --version 0.1.0
rvn pkg maven install com.example:app:0.1.0
```
