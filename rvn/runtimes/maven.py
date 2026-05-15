"""Install Apache Maven from the official Apache archive.

Downloads from: https://archive.apache.org/dist/maven/maven-3/{version}/binaries/
                apache-maven-{version}-bin.tar.gz

Installs to: ~/.rvn/runtimes/maven/<version>/

Maven requires Java to run.  If no rvn-managed Java is found, a warning is
printed but installation proceeds — the caller must ensure JAVA_HOME is set.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import httpx

from ._install import (
    RUNTIMES_DIR,
    check_linux_x64,
    download,
    extract,
    write_env_file,
    write_shim,
)


_APACHE_BASE = "https://archive.apache.org/dist/maven"

# Fallback known-good version when "latest" is requested
_DEFAULT_VERSION = "3.9.9"


def _resolve_latest() -> str:
    """Try to discover the latest Maven 3.x release from the Apache directory listing."""
    url = f"{_APACHE_BASE}/maven-3/"
    try:
        with httpx.Client(timeout=15.0) as hx:
            resp = hx.get(url)
            resp.raise_for_status()
        # Parse plain directory listing: lines like '3.9.6/'
        import re

        versions = re.findall(r'href="([\d.]+)/"', resp.text)
        if versions:
            return sorted(versions, key=lambda v: [int(x) for x in v.split(".")])[-1]
    except Exception:
        pass
    return _DEFAULT_VERSION


def install(version: str = "latest") -> Path:
    """Download and install Apache Maven *version* to ``~/.rvn/runtimes/maven/``.

    *version* may be ``"latest"`` or a full version string like ``"3.9.6"``.
    Returns the installation directory.
    """
    check_linux_x64()

    if version.lower() == "latest":
        print("Resolving latest Maven version ...", flush=True)
        version = _resolve_latest()

    dest = RUNTIMES_DIR / "maven" / version
    if dest.exists():
        print(f"Maven {version} already installed at {dest}")
        return dest

    major = version.split(".")[0]
    url = f"{_APACHE_BASE}/maven-{major}/{version}/binaries/apache-maven-{version}-bin.tar.gz"
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / url.split("/")[-1]
        download(url, archive)
        extract(archive, dest)

    mvn_bin = dest / "bin" / "mvn"
    if mvn_bin.exists():
        mvn_bin.chmod(0o755)
        write_shim("mvn", mvn_bin)
        write_shim("mvnw", mvn_bin)

    # Check that Java is available
    import shutil

    if not shutil.which("java"):
        java_base = RUNTIMES_DIR / "java"
        if not java_base.exists() or not any(java_base.iterdir()):
            print(
                "  Warning: no Java found. Maven requires Java to run.\n"
                "  Install with: rvn system install java 21",
                file=sys.stderr,
            )

    write_env_file()
    print(f"✓ Maven {version} installed at {dest}")
    print("  Add to PATH:  source ~/.rvn/env")
    return dest


def list_installed() -> list[tuple[str, Path]]:
    """Return [(version, path), ...] for all rvn-managed Maven installations."""
    base = RUNTIMES_DIR / "maven"
    if not base.exists():
        return []
    return sorted(
        [(p.name, p) for p in base.iterdir() if p.is_dir()],
        key=lambda t: t[0],
    )


def find(version_prefix: str = "") -> Path | None:
    """Return the path of the first installed Maven matching *version_prefix*.

    If *version_prefix* is empty, return the latest installed version.
    """
    installed = list_installed()
    if not installed:
        return None
    if version_prefix:
        vp = version_prefix.rstrip(".")
        for ver, path in installed:
            if ver == vp or ver.startswith(vp + "."):
                return path
        return None
    return installed[-1][1]


def mvn_bin(version_prefix: str = "") -> Path | None:
    """Return the ``mvn`` binary path for *version_prefix*, or None."""
    base = find(version_prefix)
    return (base / "bin" / "mvn") if base else None
