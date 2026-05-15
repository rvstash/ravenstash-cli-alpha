"""Tool resolver — managed runtimes first, system PATH fallback.

Every place in rvn that shells out to a package manager (mvn, npm, pip, uv…)
should use :func:`require` instead of a bare string so that:

1. rvn-managed runtimes (installed via ``rvn system install``) take priority
   over whatever happens to be on the system PATH.
2. A clear, actionable error is shown when the tool is genuinely missing,
   rather than a raw ``FileNotFoundError``.

Managed runtime layout (``~/.rvn/runtimes/``)
----------------------------------------------
- ``python/<version>/bin/python3``, ``pip3``  — via python-build-standalone
- ``node/<version>/bin/node``, ``npm``, ``npx`` — via nodejs.org tarballs
- ``maven/<version>/bin/mvn``                 — via Apache Maven archives
- (``java/<version>/bin/java`` — JRE only, not a package tool)

Usage
-----
    from ..runtimes import tools

    subprocess.run([tools.require("mvn", install_kind="maven"), "--version"])
    subprocess.run([tools.require("npm", install_kind="node"), "install"])
    subprocess.run([tools.require("pip", install_kind="python"), "install", ...])
    subprocess.run([tools.require("uv", install_kind="uv"), "sync"])

    # When the tool is optional and you want to handle absence yourself:
    path = tools.resolve("mvn")
    if path:
        subprocess.run([path, ...])
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


# ── helpers ────────────────────────────────────────────────────────────────────


def _managed_node_dir() -> Path | None:
    """Return the ``bin/`` dir of the latest managed Node.js install, or None."""
    from .node import find

    base = find("")
    return (base / "bin") if base else None


def _managed_python_dir() -> Path | None:
    """Return the ``bin/`` dir of the latest managed Python install, or None."""
    from .python import find

    base = find("")
    return (base / "bin") if base else None


def _managed_mvn() -> str | None:
    """Return the path to the managed ``mvn`` binary, or None."""
    from .maven import mvn_bin

    p = mvn_bin()
    return str(p) if p and p.exists() else None


def _managed_uv() -> str | None:
    """Return the path to a managed ``uv`` binary from the rvn tools dir, or None."""
    from ._install import TOOLS_DIR

    candidate = TOOLS_DIR / "uv" / "uv"
    return str(candidate) if candidate.exists() else None


# ── public API ─────────────────────────────────────────────────────────────────


def resolve(name: str) -> str | None:
    """Return an absolute path to *name* — managed runtime first, then system PATH.

    Returns ``None`` if the tool is not found anywhere.
    """
    # ── npm / npx / node — from managed Node.js ──────────────────────────────
    if name in ("npm", "npx", "node"):
        node_dir = _managed_node_dir()
        if node_dir:
            candidate = node_dir / name
            if candidate.exists():
                return str(candidate)

    # ── pip / pip3 / python / python3 — from managed Python ──────────────────
    if name in ("pip", "pip3", "python", "python3"):
        py_dir = _managed_python_dir()
        if py_dir:
            # pip3 / pip may be named exactly or versioned (pip3.12)
            for n in (name, "pip3", "pip"):
                candidate = py_dir / n
                if candidate.exists():
                    return str(candidate)

    # ── mvn — from managed Maven ──────────────────────────────────────────────
    if name == "mvn":
        managed = _managed_mvn()
        if managed:
            return managed

    # ── uv — from managed uv (standalone binary, rvn-downloaded) ─────────────
    if name == "uv":
        managed = _managed_uv()
        if managed:
            return managed

    # ── system PATH fallback ──────────────────────────────────────────────────
    return shutil.which(name)


def require(name: str, *, install_kind: str) -> str:
    """Like :func:`resolve` but exits with an actionable install hint if missing.

    ``install_kind`` is the argument to ``rvn system install`` that would
    install the missing tool, e.g. ``"maven"``, ``"node"``, ``"python"``,
    ``"uv"``.

    Example::

        subprocess.run([require("mvn", install_kind="maven"), "clean", "install"])
    """
    path = resolve(name)
    if path:
        return path

    # Lazy import to avoid circular dependency at module load time.
    from .. import output

    output.fatal(
        f"'{name}' is not installed and was not found on PATH.\n"
        f"  Install it via rvn:  rvn system install {install_kind}\n"
        f"  Or install it system-wide and ensure it is on your PATH."
    )


# ── convenience wrappers ───────────────────────────────────────────────────────
#
# These return the resolved binary name for the four main toolchains.
# Use them to build subprocess commands:
#
#   subprocess.run([tools.mvn(), "--version"])
#


def mvn() -> str:
    """Return the resolved ``mvn`` binary path (managed or system)."""
    return require("mvn", install_kind="maven")


def npm() -> str:
    """Return the resolved ``npm`` binary path (managed or system)."""
    return require("npm", install_kind="node")


def pip() -> str:
    """Return the resolved ``pip`` / ``pip3`` binary path (managed or system)."""
    # Prefer uv pip when uv is available — it's a drop-in, much faster.
    uv_path = resolve("uv")
    if uv_path:
        return uv_path  # caller must prefix args with "pip"

    return require("pip", install_kind="python")


def uv() -> str:
    """Return the resolved ``uv`` binary path (managed or system)."""
    return require("uv", install_kind="uv")


def pip_cmd() -> list[str]:
    """Return ``["uv", "pip"]`` when uv is available, else ``["pip"]``.

    Use as the command prefix::

        subprocess.run([*tools.pip_cmd(), "install", "requests"])
    """
    uv_path = resolve("uv")
    if uv_path:
        return [uv_path, "pip"]
    pip_path = resolve("pip") or resolve("pip3")
    if pip_path:
        return [pip_path]
    require("pip", install_kind="python")  # will fatal()
    return ["pip"]  # unreachable, satisfies type-checker
