# rvn-demo-python

Minimal Python project for hands-on testing of `rvn` CLI commands.

## What's in here

| File | Purpose |
|------|---------|
| `pyproject.toml` | Real PEP 517 project with httpx, rich, pydantic, typer |
| `src/rvn_demo/main.py` | Tiny CLI that hits the public PyPI JSON API |

## Try it — public registry, no account needed

```bash
# 1. Pin and install Python runtime
rvn python pin 3.12          # falls back to python-build-standalone if uv not found

# 2. Create virtual environment
rvn python venv              # creates .venv/

# 3. Activate (or use 'rvn run' to avoid activating)
source .venv/bin/activate

# 4. Install dependencies from public PyPI
rvn pypi install             # pip install -e .[dev]

# 5. Inspect the environment
rvn pypi freeze              # pip freeze
rvn pypi show httpx          # pip show httpx
rvn pypi show pydantic
rvn pypi outdated            # pip list --outdated

# 6. Run the demo app
rvn-demo info httpx
rvn-demo info rich --json
rvn-demo versions typer --limit 5

# 7. Run linters / type checkers via rvnx (no global install needed)
rvnx ruff check src/
rvnx black --check src/
rvnx mypy src/
```

## Try it — private registry (needs rvn auth login)

```bash
# Login first
rvn auth login --api-url https://api.ravenstash.com

# Publish to your private PyPI repo
rvn pypi publish --repo my-pypi-repo

# Bump version
rvn pypi bump patch          # edits pyproject.toml: 0.1.0 → 0.1.1

# Manage dist-tags (pre-release / stable)
rvn pypi dist-tag ls  --repo my-pypi-repo --name rvn-demo-python
rvn pypi dist-tag add --repo my-pypi-repo --name rvn-demo-python --version 0.2.0 --tag beta

# Yank a broken release
rvn pypi yank --repo my-pypi-repo --name rvn-demo-python --version 0.1.0

# Snapshot (dev / pre-release publish)
rvn pypi snapshot publish --repo my-pypi-repo
rvn pypi snapshot ls     --repo my-pypi-repo --name rvn-demo-python
```
