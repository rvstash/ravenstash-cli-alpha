"""Install Node.js runtimes from the official nodejs.org binary distribution.

Downloads from: https://nodejs.org/dist/v{version}/node-v{version}-linux-{arch}.tar.xz

Installs to: ~/.rvs/runtimes/node/<full_version>/
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import httpx

from .. import output
from ._install import (
    RUNTIMES_DIR,
    check_linux_x64,
    download,
    extract,
    write_env_file,
    write_shim,
)
from .versions import version_key


_INDEX_URL = "https://nodejs.org/dist/index.json"

# nodejs.org arch strings
_ARCH_MAP = {"x64": "x64", "aarch64": "arm64"}


def _resolve_full_version(version: str) -> str:
    """Resolve a partial version (``"20"``, ``"20.11"``) to the full release string."""
    output.info("Fetching Node.js release index ...")
    with httpx.Client(timeout=30.0) as hx:
        resp = hx.get(_INDEX_URL)
        resp.raise_for_status()
        releases: list[dict[str, Any]] = resp.json()

    # Normalise: strip leading 'v'
    vp = version.lstrip("v").rstrip(".")

    # Try exact match first, then prefix match
    for rel in releases:
        v = rel["version"].lstrip("v")
        if v == vp or v.startswith(vp + "."):
            return v

    # Match by major version only
    try:
        major = int(vp.split(".")[0])
    except ValueError:
        output.fatal(f"Cannot resolve Node.js version '{version}'.")

    for rel in releases:
        v = rel["version"].lstrip("v")
        if int(v.split(".")[0]) == major:
            return v

    output.fatal(f"No Node.js release found for '{version}'.")


def install(version: str) -> Path:
    """Download and install Node.js *version* to ``~/.rvs/runtimes/node/``.

    *version* may be a major (``"20"``), major.minor (``"20.11"``), or full
    version string (``"20.11.0"``).  Returns the installation directory.
    """
    _, arch_raw = check_linux_x64()
    arch = _ARCH_MAP.get(arch_raw, arch_raw)

    if version.lower() == "latest":
        version = "current"  # nodejs.org uses 'current' for the latest release

    full_ver = _resolve_full_version(version)
    dest = RUNTIMES_DIR / "node" / full_ver

    if dest.exists():
        output.info(f"Node.js {full_ver} already installed at {dest}")
        return dest

    url = f"https://nodejs.org/dist/v{full_ver}/node-v{full_ver}-linux-{arch}.tar.xz"
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / url.split("/")[-1]
        download(url, archive)
        extract(archive, dest)

    bin_dir = dest / "bin"
    for exe in ("node", "npm", "npx", "corepack"):
        if (bin_dir / exe).exists():
            write_shim(exe, bin_dir / exe, runtime_kind="node")

    write_env_file()
    output.success(f"Node.js {full_ver} installed at {dest}")
    output.info("Add to PATH: source ~/.rvs/env")
    return dest


def list_installed() -> list[tuple[str, Path]]:
    """Return [(version, path), ...] for all rvs-managed Node.js installations."""
    base = RUNTIMES_DIR / "node"
    if not base.exists():
        return []
    return sorted(
        [(p.name, p) for p in base.iterdir() if p.is_dir()],
        key=lambda t: version_key(t[0]),
    )


def find(version_prefix: str) -> Path | None:
    """Return the newest installed Node.js matching *version_prefix*."""
    vp = version_prefix.lstrip("v").rstrip(".")
    if not vp:
        installed = list_installed()
        return installed[-1][1] if installed else None
    matches = [path for ver, path in list_installed() if ver == vp or ver.startswith(vp + ".")]
    return matches[-1] if matches else None


def node_bin(version_prefix: str) -> Path | None:
    """Return the ``node`` binary path for *version_prefix*, or None."""
    base = find(version_prefix)
    return (base / "bin" / "node") if base else None
