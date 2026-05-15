"""Install Node.js runtimes from the official nodejs.org binary distribution.

Downloads from: https://nodejs.org/dist/v{version}/node-v{version}-linux-{arch}.tar.xz

Installs to: ~/.rvn/runtimes/node/<full_version>/
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx

from ._install import (
    RUNTIMES_DIR,
    check_linux_x64,
    download,
    extract,
    write_env_file,
    write_shim,
)


_INDEX_URL = "https://nodejs.org/dist/index.json"

# nodejs.org arch strings
_ARCH_MAP = {"x64": "x64", "aarch64": "arm64"}


def _resolve_full_version(version: str) -> str:
    """Resolve a partial version (``"20"``, ``"20.11"``) to the full release string."""
    print("Fetching Node.js release index ...", flush=True)
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
        print(f"Cannot resolve Node.js version '{version}'.", file=sys.stderr)
        sys.exit(1)

    for rel in releases:
        v = rel["version"].lstrip("v")
        if int(v.split(".")[0]) == major:
            return v

    print(f"No Node.js release found for '{version}'.", file=sys.stderr)
    sys.exit(1)


def install(version: str) -> Path:
    """Download and install Node.js *version* to ``~/.rvn/runtimes/node/``.

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
        print(f"Node.js {full_ver} already installed at {dest}")
        return dest

    url = f"https://nodejs.org/dist/v{full_ver}/node-v{full_ver}-linux-{arch}.tar.xz"
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / url.split("/")[-1]
        download(url, archive)
        extract(archive, dest)

    bin_dir = dest / "bin"
    for exe in ("node", "npm", "npx", "corepack"):
        if (bin_dir / exe).exists():
            write_shim(exe, bin_dir / exe)

    write_env_file()
    print(f"✓ Node.js {full_ver} installed at {dest}")
    print("  Add to PATH:  source ~/.rvn/env")
    return dest


def list_installed() -> list[tuple[str, Path]]:
    """Return [(version, path), ...] for all rvn-managed Node.js installations."""
    base = RUNTIMES_DIR / "node"
    if not base.exists():
        return []
    return sorted(
        [(p.name, p) for p in base.iterdir() if p.is_dir()],
        key=lambda t: t[0],
    )


def find(version_prefix: str) -> Path | None:
    """Return the path of the first installed Node.js matching *version_prefix*."""
    vp = version_prefix.lstrip("v").rstrip(".")
    for ver, path in list_installed():
        if ver == vp or ver.startswith(vp + "."):
            return path
    return None


def node_bin(version_prefix: str) -> Path | None:
    """Return the ``node`` binary path for *version_prefix*, or None."""
    base = find(version_prefix)
    return (base / "bin" / "node") if base else None
