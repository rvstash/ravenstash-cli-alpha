"""Install Java runtimes using Eclipse Temurin (Adoptium project).

Uses the Adoptium REST API to discover and download the latest GA release
for a given major version.

API: https://api.adoptium.net/v3/assets/latest/{major}/ga?os=linux&...

Installs to: ~/.rvn/runtimes/java/<semver>/
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


_ADOPTIUM = "https://api.adoptium.net/v3"

# Adoptium arch strings
_ARCH_MAP = {"x64": "x64", "aarch64": "aarch64"}


def _latest_release(major: int, arch: str) -> dict[str, Any]:
    """Return the Adoptium release metadata for the latest GA JDK of *major*."""
    url = f"{_ADOPTIUM}/assets/latest/{major}/ga"
    params = {
        "architecture": arch,
        "image_type": "jdk",
        "jvm_impl": "hotspot",
        "os": "linux",
        "vendor": "eclipse",
    }
    print(f"Fetching Temurin JDK {major} metadata ...", flush=True)
    with httpx.Client(timeout=30.0) as hx:
        resp = hx.get(url, params=params)
        resp.raise_for_status()
        data: list[dict[str, Any]] = resp.json()
    if not data:
        print(f"No Temurin JDK {major} release found.", file=sys.stderr)
        sys.exit(1)
    return data[0]


def install(version: str) -> Path:
    """Download and install Temurin JDK *version* to ``~/.rvn/runtimes/java/``.

    *version* is a major version number (``"21"``) or full semver.
    Returns the installation directory.
    """
    _, arch_raw = check_linux_x64()
    arch = _ARCH_MAP.get(arch_raw, arch_raw)

    try:
        major = int(version.split(".")[0].split("+")[0])
    except ValueError:
        print(f"Cannot parse Java version '{version}'.", file=sys.stderr)
        sys.exit(1)

    release = _latest_release(major, arch)
    binary_meta = release.get("binary", {})
    pkg = binary_meta.get("package", {})
    dl_url: str = pkg.get("link", "")
    checksum: str | None = pkg.get("checksum")
    semver: str = release.get("version", {}).get("semver", version)

    dest = RUNTIMES_DIR / "java" / semver
    if dest.exists():
        print(f"Java {semver} already installed at {dest}")
        return dest

    with tempfile.TemporaryDirectory() as tmp:
        fname = dl_url.split("/")[-1].split("?")[0] or f"jdk-{semver}.tar.gz"
        archive = Path(tmp) / fname
        download(dl_url, archive, expected_sha256=checksum)
        extract(archive, dest)

    bin_dir = dest / "bin"
    for exe in ("java", "javac", "jar", "javadoc"):
        if (bin_dir / exe).exists():
            write_shim(exe, bin_dir / exe)

    write_env_file()
    print(f"✓ Java {semver} (Temurin) installed at {dest}")
    print(f"  Set JAVA_HOME: export JAVA_HOME={dest}")
    print("  Add to PATH:   source ~/.rvn/env")
    return dest


def list_installed() -> list[tuple[str, Path]]:
    """Return [(version, path), ...] for all rvn-managed Java installations."""
    base = RUNTIMES_DIR / "java"
    if not base.exists():
        return []
    return sorted(
        [(p.name, p) for p in base.iterdir() if p.is_dir()],
        key=lambda t: t[0],
    )


def find(version_prefix: str) -> Path | None:
    """Return the path of the first installed Java matching *version_prefix*."""
    vp = version_prefix.rstrip(".")
    if not vp:
        installed = list_installed()
        return installed[-1][1] if installed else None
    for ver, path in list_installed():
        if ver == vp or ver.startswith(vp + ".") or ver.startswith(vp + "+"):
            return path
    return None


def java_bin(version_prefix: str) -> Path | None:
    """Return the ``java`` binary path for *version_prefix*, or None."""
    base = find(version_prefix)
    return (base / "bin" / "java") if base else None
