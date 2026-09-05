# rvs-demo-python

Minimal Python project for testing the alpha `rvs` package repository commands.

## Local Work

```bash
cd examples/python
rvs runtime use python 3.12
python -m pip install -e .[dev]

rvs-demo info httpx
rvs-demo info rich --json
rvs-demo versions typer --limit 5
```

Use normal Python packaging tools to build distributions into `dist/`.

## Ravenstash Package Repository

```bash
rvs auth login
rvs art repo create my-python-packages --ecosystem pypi --default
rvs art pypi index-url
rvs art pypi configure
rvs art pypi publish dist/
rvs art package list --repo <repo-name>
```

To install from a private Ravenstash PyPI repository:

```bash
rvs art pypi install rvs-demo-python --repo <repo-name>
```
