# rvn examples

Three self-contained demo projects for exercising the `rvn` CLI against public
registries and the built-in runtime manager.  None of them require a Ravenstash
account for the commands marked **public**.  Commands marked **private** need
`rvn auth login` first.

```
examples/
├── python/   PyPI project — httpx, rich, pydantic, typer
├── npm/      npm project  — axios, lodash, chalk, dotenv
└── java/     Maven project — jackson-databind, slf4j, commons-lang3
```

---

## Quick-start: install runtimes (once, no system tools needed)

```bash
# Downloads self-contained binaries into ~/.rvn/runtimes/
rvn system install python 3.12
rvn system install node 20
rvn system install java 21
rvn system install maven latest

# Add shims to PATH (do once, then restart your shell)
rvn system setup-shell
source ~/.rvn/env

# Verify
rvn system list
```

---

## Python example

```bash
cd examples/python

# Pin runtime for the project (writes .python-version)
rvn python pin 3.12

# Create virtual environment
rvn python venv

# PUBLIC — install deps from public PyPI
rvn pypi install                        # pip install -r / uv sync
rvn pypi show httpx                     # pip show httpx
rvn pypi freeze                         # pip freeze
rvn pypi outdated                       # pip list --outdated

# PUBLIC — try rvnx (run a tool without installing it globally)
rvnx ruff check src/
rvnx black --check src/
rvnx mypy src/

# PRIVATE — publish to Ravenstash (needs login + repo)
rvn pypi publish --repo my-pypi-repo    # build + twine upload
rvn pypi bump patch                     # bumps version in pyproject.toml
rvn pypi dist-tag ls --repo my-pypi-repo --name rvn-demo-python
```

---

## npm example

```bash
cd examples/npm

# Pin runtime
rvn node pin 20

# PUBLIC — install deps from public npm registry
rvn npm install                         # npm install
rvn npm view lodash                     # npm view lodash
rvn npm ls                              # npm ls
rvn npm outdated                        # npm outdated

# PUBLIC — try npx-style runner
rvnx --npm prettier --check src/

# PRIVATE — publish to Ravenstash (needs login + repo)
rvn npm publish --repo my-npm-repo
rvn npm bump patch                      # npm version patch
rvn npm dist-tag ls --repo my-npm-repo --name rvn-demo-npm
```

---

## Java / Maven example

```bash
cd examples/java

# Pin runtimes
rvn java pin 21
rvn system install maven latest         # or: rvn system install maven 3.9.9

# PUBLIC — resolve deps from Maven Central
rvn maven install                       # mvn dependency:get / resolve
rvn maven list                          # mvn dependency:list

# PUBLIC — print the registry URL for settings.xml
rvn maven repo-url --repo my-maven-repo     # (shows what URL would be used)
rvn maven settings-xml --repo my-maven-repo # (shows settings.xml snippet)

# PRIVATE — publish to Ravenstash (needs login + repo)
rvn maven deploy --repo my-maven-repo   # mvn deploy:deploy-file
rvn maven bump patch                    # mvn versions:set
```

---

## Auth flow (for private commands)

```bash
# Login to your Ravenstash instance
rvn auth login --api-url https://api.ravenstash.com

# Or for a self-hosted instance
rvn auth add-registry pypi \
    --api-url https://api.myinstance.com \
    --token <your-token>

# Verify
rvn auth status
rvn auth list
```
