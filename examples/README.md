# rvs Examples

These projects are small package examples for trying the current alpha `rvs`
surface. They are ordinary Python, npm, and Maven projects; use native tooling
for local build/test work, and use `rvs pkg` when interacting with a private
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
rvs pkg repo list
rvs pkg repo create my-python-packages --kind pypi --default
rvs pkg repo create my-node-packages --kind npm --default
rvs pkg repo create my-java-packages --kind maven --default
```

`rvs pkg` expects package repository names, such as `my-python-packages`.
After a repository is set as the default for its kind, the `--repo` flag can be
omitted for that kind.

## Package Helpers

```bash
rvs pkg pypi index-url
rvs pkg pypi publish dist/
rvs pkg pypi install my-private-package

rvs pkg npm registry-url
rvs pkg npm publish .
rvs pkg npm install my-private-package

rvs pkg maven repo-url
rvs pkg maven deploy target/app.jar --group com.example --artifact app --version 0.1.0
rvs pkg maven install com.example:app:0.1.0
```
