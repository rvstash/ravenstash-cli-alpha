# rvn-demo-python

Minimal Python project for testing the alpha `rvn` package repository commands.

## Local Work

```bash
cd examples/python
rvn runtime use python 3.12
python -m pip install -e .[dev]

rvn-demo info httpx
rvn-demo info rich --json
rvn-demo versions typer --limit 5
```

Use normal Python packaging tools to build distributions into `dist/`.

## Ravenstash Package Repository

```bash
rvn auth login
rvn pkg repo create my-python-packages --kind pypi --default
rvn pkg pypi index-url
rvn pkg pypi configure
rvn pkg pypi publish dist/
rvn pkg package list --repo <repository-id>
```

To install from a private Ravenstash PyPI repository:

```bash
rvn pkg pypi install rvn-demo-python --repo <repository-id>
```
