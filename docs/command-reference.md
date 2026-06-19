# rvn Command Reference

Universal CLI for Ravenstash private registries — Python (PyPI), JavaScript (npm), and Java (Maven).

## Quick overview

| Command group | Purpose |
|---|---|
| `rvn auth` | Multi-registry login, logout, per-kind overrides |
| `rvn pypi` | PyPI registry — full ecosystem lifecycle |
| `rvn npm` | npm registry — full ecosystem lifecycle |
| `rvn maven` | Maven registry — full ecosystem lifecycle |
| `rvn python` | Python runtime management (pin, venv) |
| `rvn node` | Node.js runtime management (pin) |
| `rvn java` | Java runtime management (pin) |
| `rvn sync / add / remove / venv` | Universal auto-detect project commands |
| `rvn auth / repos / packages / tokens` | Authentication, profile, and management commands |

## Feature support matrix

| Feature | `rvn pypi` | `rvn npm` | `rvn maven` |
|---|---|---|---|
| Install / fetch | ✅ canonical | ✅ canonical | ✅ canonical |
| Publish / deploy | ✅ canonical | ✅ canonical | ✅ canonical |
| Yank | ✅ webapp API | ✅ webapp API | ✅ webapp API |
| Deprecate | ❌ not in PyPI | ✅ canonical (`npm deprecate`) | ✅ webapp API |
| Bump version | ✅ pyproject.toml / regex | ✅ `npm version` | ✅ `mvn versions:set` |
| dist-tag ls | ✅ webapp API | ✅ canonical (`npm dist-tag`) | ✅ webapp API |
| dist-tag add/rm | ✅ webapp API | ✅ canonical (`npm dist-tag`) | ✅ webapp API |
| Snapshot publish | ✅ pre-release version | ✅ `--tag snapshot` | ✅ `-SNAPSHOT` suffix |
| Snapshot list | ✅ webapp API | ✅ `npm view dist-tags` | ✅ webapp API |
| Multi-registry auth | ✅ per-kind override | ✅ per-kind override | ✅ per-kind override |

**Legend:** ✅ canonical = works via native protocol URLs (fully functional). ✅ webapp API = goes through the Ravenstash management API (may degrade gracefully with 404 on older servers). ❌ = not supported by the registry protocol.

---

## rvn auth — Authentication

### `rvn auth login`

Interactive login to a Ravenstash instance.

```
$ rvn auth login
Device code: ABCD-1234
Open this URL and enter the code to approve the device: https://app.ravenstash.com/login/device
Open the link in your browser, or CTRL+CLICK it from your terminal.
✓ Authenticated profile 'default' with a temporary credential.
```

```
$ rvn auth login --profile work --api-url https://api.mycompany.com
Device code: WXYZ-9876
Open this URL and enter the code to approve the device: https://app.mycompany.com/login/device
✓ Authenticated profile 'work' with a temporary credential.
```

`rvn` stores only the short-lived CLI JWT in the OS keyring. PAT/M2M credentials
belong in `RVN_TOKEN`; that env var always takes precedence over local profiles.

### `rvn auth logout`

```
$ rvn auth logout
✓ Credentials removed for profile 'default'.

$ rvn auth logout --profile work
✓ Credentials removed for profile 'work'.

$ rvn auth logout --all
✓ Credentials removed for all profiles.
```

### `rvn auth switch`

```
$ rvn auth switch
# Opens an interactive profile picker. Use ↑/↓ and ENTER to confirm.

$ rvn auth switch --profile work
✓ Active profile set to 'work'.
```

### `rvn auth delete`

```
$ rvn auth delete
✓ Profile 'default' deleted.

$ rvn auth delete --profile work
✓ Profile 'work' deleted.

$ rvn auth delete --all
✓ All profiles deleted.
```

### `rvn auth add-registry`

Configure per-kind overrides: separate API URL or default repo for PyPI, npm, or Maven.

```
$ rvn auth add-registry --kind pypi \
    --api-url https://api.myhost.com \
    --repo my-pypi
✓ Registry 'pypi' updated: api-url=https://api.myhost.com, repo=my-pypi

$ rvn auth add-registry --kind npm --repo my-npm
✓ Registry 'npm' updated: repo=my-npm
```

### `rvn auth list`

```
$ rvn auth list

Profiles
┌──────────────────┬────────────────────────────┬─────────────┬───────────────────┐
│ Profile          │ API URL                    │ Customer    │ Credential source │
├──────────────────┼────────────────────────────┼─────────────┼───────────────────┤
│ default (active) │ https://api.ravenstash.com │ cus_default │ keyring           │
│ work             │ https://api.mycompany.com  │ cus_work    │ RVN_TOKEN         │
└──────────────────┴────────────────────────────┴─────────────┴───────────────────┘

Per-kind registry overrides
┌────────┬──────────────┬─────────────────────────────┬────────────────┐
│ Kind   │ Default repo │ API URL override             │ Token          │
├────────┼──────────────┼─────────────────────────────┼────────────────┤
│ pypi   │ my-pypi      │ https://api.myhost.com       │ (uses profile) │
│ npm    │ my-npm       │ (uses profile)               │ (uses profile) │
│ maven  │ (not set)    │ (uses profile)               │ (uses profile) │
└────────┴──────────────┴─────────────────────────────┴────────────────┘
```

### `rvn auth status`

```
$ rvn auth status
Authentication status
Profile:         default
API URL:         https://api.ravenstash.com
Token source:    keyring
Credential type: temporary
Customer:        cus_default
Expires at:      2026-06-18T16:00:00+00:00

$ rvn auth status --profile work
Authentication status
Profile:         work
API URL:         https://api.mycompany.com
Token source:    keyring
Credential type: temporary
Customer:        cus_work
Expires at:      2026-06-18T16:00:00+00:00
```

---

## rvn pypi — Python / PyPI registry

### Install

```
$ rvn pypi install requests --repo my-pypi
# → uv pip install requests --index-url https://api.ravenstash.com/pypi/r/my-pypi/simple/

$ rvn pypi install "requests>=2.28" django==5.0 --repo my-pypi
# installs multiple packages from private registry
```

### Download

```
$ rvn pypi download requests --repo my-pypi --dest ./dist-cache
✓ Downloaded requests-2.31.0-py3-none-any.whl
```

### Show / list

```
$ rvn pypi show requests --repo my-pypi
Name:    requests
Version: 2.31.0
Summary: Python HTTP for Humans.
Author:  Kenneth Reitz

$ rvn pypi list --repo my-pypi
┌──────────────┬─────────┐
│ Package      │ Version │
├──────────────┼─────────┤
│ requests     │ 2.31.0  │
│ django       │ 5.0.2   │
│ numpy        │ 1.26.4  │
└──────────────┴─────────┘
```

### Freeze

```
$ rvn pypi freeze --repo my-pypi
requests==2.31.0
django==5.0.2
numpy==1.26.4
```

### Sync (project-aware)

```
$ rvn pypi sync
# Reads pyproject.toml, runs: uv sync --frozen
✓ Sync complete.
```

### Add / remove

```
$ rvn pypi add "httpx>=0.27" --repo my-pypi
✓ Added 'httpx>=0.27' to pyproject.toml

$ rvn pypi remove httpx
✓ Removed 'httpx' from pyproject.toml
Run `rvn pypi sync` to update your environment.
```

### Publish

```
$ rvn pypi publish dist/ --repo my-pypi
✓ Published mypackage-1.0.0-py3-none-any.whl (1.0.0)
✓ Published mypackage-1.0.0.tar.gz (1.0.0)
```

### Yank

```
$ rvn pypi yank mypackage 1.0.0 --repo my-pypi
✓ Yanked mypackage==1.0.0.

$ rvn pypi yank mypackage 1.0.0 --reason "Contains a critical bug" --repo my-pypi
✓ Yanked mypackage==1.0.0.
  Reason: Contains a critical bug
```

### Deprecate

```
$ rvn pypi deprecate mypackage 1.0.0 "Use mypackage>=2.0" --repo my-pypi
Error: PyPI does not support deprecation at the protocol level.
  For Python packages, use 'yank' to hide a specific version:
    rvn pypi yank mypackage 1.0.0
  Or publish a new version with an updated deprecation notice in the README.
```

### Bump version

```
$ rvn pypi bump patch
# reads pyproject.toml: version = "1.2.3"
✓ Bumped version: 1.2.3 → 1.2.4

$ rvn pypi bump minor
✓ Bumped version: 1.2.3 → 1.3.0

$ rvn pypi bump major
✓ Bumped version: 1.2.3 → 2.0.0
```

### dist-tag ls / add / rm

PyPI has no native dist-tag support. These commands call the Ravenstash management API (requires server-side support; graceful 404 on older instances).

```
$ rvn pypi dist-tag ls mypackage --repo my-pypi
┌────────┬─────────┐
│ Tag    │ Version │
├────────┼─────────┤
│ stable │ 1.5.0   │
│ lts    │ 1.4.2   │
└────────┴─────────┘

$ rvn pypi dist-tag add mypackage==2.0.0 stable --repo my-pypi
✓ Tagged mypackage==2.0.0 as 'stable'.

$ rvn pypi dist-tag rm mypackage lts --repo my-pypi
✓ Removed tag 'lts' from mypackage.
```

### Snapshot publish / ls

PyPI snapshots are pre-release versions (`.dev`, `.a`, `.b`, `.rc`).

```
$ rvn pypi snapshot publish dist/ --repo my-pypi
# version must be a pre-release (e.g. 1.1.0.dev3, 2.0.0a1)
✓ Snapshot 1.1.0.dev3 published.

$ rvn pypi snapshot ls mypackage --repo my-pypi
┌──────────────────┐
│ Snapshot version │
├──────────────────┤
│ 1.1.0.dev3       │
│ 1.0.0a1          │
│ 1.0.0rc2         │
└──────────────────┘
```

### Registry URL helpers

```
$ rvn pypi index-url --repo my-pypi
https://api.ravenstash.com/pypi/r/my-pypi/simple/

$ rvn pypi upload-url --repo my-pypi
https://api.ravenstash.com/pypi/r/my-pypi/
```

---

## rvn npm — JavaScript / npm registry

### Install

```
$ rvn npm install lodash --repo my-npm
# → npm install lodash --registry https://api.ravenstash.com/npm/r/my-npm/

$ rvn npm install lodash@4 @scope/utils --save-dev --repo my-npm
```

### CI

```
$ rvn npm ci --repo my-npm
# → npm ci --registry https://api.ravenstash.com/npm/r/my-npm/
```

### View / ls / outdated

```
$ rvn npm view lodash --repo my-npm
# → npm view lodash --registry <url>

$ rvn npm ls --repo my-npm
# → npm ls --registry <url>

$ rvn npm outdated --repo my-npm
# → npm outdated --registry <url>
```

### Sync

```
$ rvn npm sync --repo my-npm
# Detects yarn.lock / pnpm-lock.yaml; defaults to npm ci
Running: npm ci
✓ Sync complete.

$ rvn npm sync --no-frozen --repo my-npm
Running: npm install
✓ Sync complete.
```

### Add / remove

```
$ rvn npm add lodash@4 --repo my-npm
✓ Added 'lodash@4' to package.json
Running: npm install --save lodash@4

$ rvn npm add jest --dev --repo my-npm
✓ Added 'jest' to package.json (devDependencies)

$ rvn npm remove lodash
✓ Removed 'lodash'.
```

### Publish

```
$ rvn npm publish --repo my-npm
✓ Published my-package@1.0.0

$ rvn npm publish --tag beta --repo my-npm
✓ Published my-package@2.0.0-beta.1
```

### Yank

npm has no native yank concept. Goes through the Ravenstash webapp API.

```
$ rvn npm yank my-package 1.0.0 --repo my-npm
✓ Yanked my-package@1.0.0.

$ rvn npm yank my-package 1.0.0 --reason "Security vulnerability" --repo my-npm
✓ Yanked my-package@1.0.0.
  Reason: Security vulnerability
```

### Deprecate

```
$ rvn npm deprecate "my-package@<2.0.0" "Use my-package@2 instead" --repo my-npm
# → npm deprecate "my-package@<2.0.0" "Use my-package@2 instead" --registry <url>
✓ Deprecated my-package@<2.0.0.

$ rvn npm deprecate my-package@1.0.0 "Use 1.0.1" --repo my-npm
✓ Deprecated my-package@1.0.0.
```

### Bump version

```
$ rvn npm bump patch
# package.json: "version": "1.2.3"
Running: npm version patch
✓ Bumped to v1.2.4.

$ rvn npm bump minor --no-git-tag
Running: npm version minor --no-git-tag-version
✓ Bumped to v1.3.0.
```

### dist-tag ls / add / rm

npm dist-tags are a native registry concept. These delegate to the canonical `npm dist-tag` CLI.

```
$ rvn npm dist-tag ls my-package --repo my-npm
# → npm dist-tag ls my-package --registry <url>
latest: 2.0.0
beta: 2.1.0-beta.1
next: 3.0.0-rc.1

$ rvn npm dist-tag add my-package@2.0.0 stable --repo my-npm
Running: npm dist-tag add my-package@2.0.0 stable --registry <url>
✓ Tagged my-package@2.0.0 as 'stable'.

$ rvn npm dist-tag rm my-package beta --repo my-npm
Running: npm dist-tag rm my-package beta --registry <url>
✓ Removed tag 'beta' from my-package.
```

### Snapshot publish / ls

npm snapshots are published with a pre-release dist-tag (`snapshot`, `next`, or custom).

```
$ rvn npm snapshot publish --repo my-npm
# → npm publish --tag snapshot --registry <url>
✓ Snapshot published with tag 'snapshot'.

$ rvn npm snapshot publish --tag next --repo my-npm
✓ Snapshot published with tag 'next'.

$ rvn npm snapshot ls my-package --repo my-npm
  snapshot → 2.1.0-snapshot.20241201

Pre-releases: my-package
┌────────────────────────────┐
│ Pre-release version        │
├────────────────────────────┤
│ 2.1.0-snapshot.20241201    │
│ 2.1.0-beta.1               │
│ 3.0.0-rc.1                 │
└────────────────────────────┘
```

### Registry URL helpers

```
$ rvn npm registry-url --repo my-npm
https://api.ravenstash.com/npm/r/my-npm/

$ rvn npm npmrc --repo my-npm
registry=https://api.ravenstash.com/npm/r/my-npm/
//api.ravenstash.com/:_authToken=${RVN_TOKEN}
```

---

## rvn maven — Java / Maven registry

### Install

```
$ rvn maven install com.google.guava:guava:33.0.0-jre --repo my-maven
Fetching com.google.guava:guava:33.0.0-jre ...
# → mvn dependency:get -Dartifact=com.google.guava:guava:33.0.0-jre --settings /tmp/rvn-settings-xxx.xml
✓ Fetched com.google.guava:guava:33.0.0-jre.
```

### Sync

```
$ rvn maven sync --repo my-maven
# Detects pom.xml → mvn dependency:resolve
# Detects build.gradle → gradle dependencies
Running: mvn dependency:resolve -q --settings /tmp/rvn-settings-xxx.xml
✓ Sync complete.
```

### Add / remove

```
$ rvn maven add com.google.guava:guava:33.0.0-jre --repo my-maven
✓ Added 'com.google.guava:guava:33.0.0-jre' to pom.xml
Running: mvn dependency:get -Dartifact=com.google.guava:guava:33.0.0-jre -q

$ rvn maven remove com.google.guava:guava
✓ Removed 'com.google.guava:guava' from pom.xml
Run `rvn maven sync` to refresh the resolved dependency tree.
```

### Deploy

```
$ rvn maven deploy mylib.jar \
    --group com.example \
    --artifact mylib \
    --version 1.0.0 \
    --repo my-maven
✓ Deployed mylib-1.0.0.jar

$ rvn maven deploy mylib.war \
    --group com.example \
    --artifact mylib \
    --version 1.0.0 \
    --packaging war \
    --repo my-maven
✓ Deployed mylib-1.0.0.war
```

### List / tree

```
$ rvn maven list --repo my-maven
# → mvn dependency:list --settings /tmp/rvn-settings-xxx.xml

$ rvn maven tree --repo my-maven
# → mvn dependency:tree --settings /tmp/rvn-settings-xxx.xml
```

### Yank

Maven has no native yank concept. Goes through the Ravenstash webapp API.

```
$ rvn maven yank com.example:mylib:1.0.0 --repo my-maven
✓ Yanked com.example:mylib:1.0.0.

$ rvn maven yank com.example:mylib:1.0.0 --reason "CVE-2024-12345" --repo my-maven
✓ Yanked com.example:mylib:1.0.0.
  Reason: CVE-2024-12345
```

### Deprecate

```
$ rvn maven deprecate com.example:mylib:1.0.0 "Use mylib:2.x instead" --repo my-maven
✓ Deprecated com.example:mylib:1.0.0.
  Message: Use mylib:2.x instead
```

### Bump version

```
$ rvn maven bump patch
# pom.xml: <version>1.2.3</version>
Running: mvn versions:set -DnewVersion=1.2.4 -DgenerateBackupPoms=false -q
✓ Bumped version: 1.2.3 → 1.2.4

$ rvn maven bump minor
✓ Bumped version: 1.2.3 → 1.3.0

$ rvn maven bump major
✓ Bumped version: 1.2.3 → 2.0.0
```

### dist-tag ls / add / rm

Maven has no native dist-tag concept. These commands use the Ravenstash management API.

```
$ rvn maven dist-tag ls com.example:mylib --repo my-maven
┌─────────┬─────────┐
│ Tag     │ Version │
├─────────┼─────────┤
│ stable  │ 1.5.0   │
│ release │ 1.4.2   │
└─────────┴─────────┘

$ rvn maven dist-tag add com.example:mylib:2.0.0 stable --repo my-maven
✓ Tagged com.example:mylib:2.0.0 as 'stable'.

$ rvn maven dist-tag rm com.example:mylib release --repo my-maven
✓ Removed tag 'release' from com.example:mylib.
```

### Snapshot deploy / ls

Maven SNAPSHOT support is a native protocol feature. Artifacts with `-SNAPSHOT` version suffix can be overwritten on every deploy.

```
$ rvn maven snapshot deploy mylib.jar \
    --group com.example \
    --artifact mylib \
    --version 1.1.0 \
    --repo my-maven
# Version becomes 1.1.0-SNAPSHOT automatically
Deploying SNAPSHOT: com.example:mylib:1.1.0-SNAPSHOT
✓ Deployed SNAPSHOT mylib-1.1.0-SNAPSHOT.jar

$ rvn maven snapshot ls com.example:mylib --repo my-maven
SNAPSHOTs: com.example:mylib
┌──────────────────────────┐
│ SNAPSHOT version         │
├──────────────────────────┤
│ 1.1.0-SNAPSHOT           │
│ 1.0.0-SNAPSHOT           │
└──────────────────────────┘
```

### Registry URL helpers

```
$ rvn maven repo-url --repo my-maven
https://api.ravenstash.com/maven/r/my-maven/

$ rvn maven settings-xml --repo my-maven
<settings>
  <servers>
    <server>
      <id>rvn</id>
      <username>__token__</username>
      <password>${RVN_TOKEN}</password>
    </server>
  </servers>
  <mirrors>
    <mirror>
      <id>rvn</id>
      <mirrorOf>*</mirrorOf>
      <url>https://api.ravenstash.com/maven/r/my-maven/</url>
    </mirror>
  </mirrors>
</settings>

$ rvn maven settings-xml --server-id mycompany --repo my-maven >> ~/.m2/settings.xml
```

---

## rvn python — Python runtime management

```
$ rvn python pin 3.14
Running: uv python install 3.14
Wrote .python-version
✓ Python 3.14 ready.

$ rvn python pin 3.12.0 --no-write-file
Running: uv python install 3.12.0
✓ Python 3.12.0 ready.

$ rvn python venv
Running: uv venv .venv
✓ Virtual environment created at .venv
  Activate with:  source .venv/bin/activate

$ rvn python venv --python 3.14
Running: uv venv .venv --python 3.14
✓ Virtual environment created at .venv
```

---

## rvn node — Node.js runtime management

```
$ rvn node pin 20
Running: fnm install 20
Wrote .node-version
✓ Node 20 installed via fnm.

$ rvn node pin 22.0.0 --no-write-file
Running: fnm install 22.0.0
✓ Node 22.0.0 installed via fnm.
```

---

## rvn java — Java runtime management

```
$ rvn java pin 21
Running: sdk install java 21
Wrote .java-version
✓ Java 21 ready.

$ rvn java pin 21.0.3 --dist tem
Running: sdk install java 21.0.3.tem
Wrote .java-version
✓ Java 21.0.3.tem ready.

$ rvn java pin 21.0.3-graalce
Running: sdk install java 21.0.3-graalce
✓ Java 21.0.3-graalce ready.

$ rvn java pin 17 --no-write-file
Running: sdk install java 17
✓ Java 17 ready.
```

---

## Universal commands

These auto-detect the project type from the manifest file in the current directory.

```
$ rvn sync
# pyproject.toml → uv sync
# package.json   → npm ci
# pom.xml        → mvn dependency:resolve

$ rvn add requests>=2.28           # Python (pyproject.toml)
$ rvn add lodash@4                  # Node (package.json)
$ rvn add com.google.guava:guava:33.0  # Java (pom.xml)

$ rvn remove requests               # remove from manifest

$ rvn venv                         # create .venv (Python projects)
$ rvn venv --python 3.14
```

---

## Routing modes

All registry ecosystem commands support a `--routing` flag:

- `canonical` (default) — uses native registry protocol URLs (`/pypi/r/{slug}/simple/`, `/npm/r/{slug}/`, `/maven/r/{slug}/`). Fully functional.
- `unified` — future unified API (raises an informative error until implemented).

```
$ rvn pypi install requests --routing canonical --repo my-pypi   # default
$ rvn npm install lodash --routing unified --repo my-npm         # not yet implemented
```

---

## Config file

Config is stored at `~/.rvn/config.toml`:

```toml
default_profile = "default"

[profiles.default]
api_url = "https://api.ravenstash.com"
customer_id = "cus_..."
credential_type = "temporary"
expires_at = "2026-06-18T16:00:00+00:00"

[profiles.work]
api_url = "https://api.mycompany.com"

[registries.pypi]
default_repo = "my-pypi"
# api_url = "https://api.other.com"   # optional per-kind URL override

[registries.npm]
default_repo = "my-npm"

[registries.maven]
default_repo = "my-maven"
```

Set defaults via CLI:

```
$ rvn auth add-registry --kind pypi --repo my-pypi
$ rvn auth add-registry --kind npm --repo my-npm
$ rvn auth add-registry --kind maven --repo my-maven
$ rvn auth add-registry --kind pypi --api-url https://...
```
