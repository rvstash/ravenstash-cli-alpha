"""Shared helpers for downloading and extracting runtime archives."""

from __future__ import annotations

import hashlib
import platform
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

import httpx

from ..paths import rvn_home


# ── Directory constants ────────────────────────────────────────────────────────

RVN_DIR = rvn_home()
RUNTIMES_DIR = RVN_DIR / "runtimes"  # ~/.rvn/runtimes/{kind}/{version}/
SHIMS_DIR = RVN_DIR / "shims"  # ~/.rvn/shims/{binary} → shim scripts
ENV_FILE = RVN_DIR / "env"  # ~/.rvn/env  (source in shell rc)


# ── Platform helpers ───────────────────────────────────────────────────────────


def check_linux_x64() -> tuple[str, str]:
    """Abort if not on Linux; return (system, arch) normalised strings.

    Returns ``(system, arch)`` where ``arch`` is one of ``"x64"`` or
    ``"aarch64"``.  Calls :func:`sys.exit` on unsupported platforms.
    """
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system != "linux":
        print(f"rvn runtime management is only supported on Linux (got {system}).", file=sys.stderr)
        sys.exit(1)
    if machine in ("x86_64", "amd64"):
        arch = "x64"
    elif machine in ("aarch64", "arm64"):
        arch = "aarch64"
    else:
        print(f"Unsupported CPU architecture: {machine}.", file=sys.stderr)
        sys.exit(1)
    return system, arch


def is_debian() -> bool:
    """Return True on Debian/Ubuntu systems."""
    return Path("/etc/debian_version").exists()


# ── Download ───────────────────────────────────────────────────────────────────


def download(url: str, dest: Path, *, expected_sha256: str | None = None) -> None:
    """Download *url* to *dest* with a simple progress indicator.

    If *expected_sha256* is provided the download is verified and
    :func:`sys.exit` is called on mismatch.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    fname = url.split("/")[-1].split("?")[0]
    print(f"  Downloading {fname} ...", flush=True)
    digest = hashlib.sha256() if expected_sha256 else None
    with httpx.stream("GET", url, follow_redirects=True, timeout=180.0) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with dest.open("wb") as fh:
            for chunk in resp.iter_bytes(65536):
                fh.write(chunk)
                if digest:
                    digest.update(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    mb_done = downloaded // (1024 * 1024)
                    mb_total = total // (1024 * 1024)
                    print(f"\r  {pct:3d}%  {mb_done} / {mb_total} MB  ", end="", flush=True)
    print()  # newline after progress bar
    if digest and expected_sha256:
        actual = digest.hexdigest()
        if actual != expected_sha256:
            dest.unlink(missing_ok=True)
            print(
                f"Checksum mismatch for {fname}:\n"
                f"  expected {expected_sha256}\n"
                f"  got      {actual}",
                file=sys.stderr,
            )
            sys.exit(1)


# ── Extract ────────────────────────────────────────────────────────────────────


def extract(archive: Path, dest: Path, *, strip_root: bool = True) -> None:
    """Extract a .tar.gz / .tar.xz archive to *dest*.

    When *strip_root* is True (default) the single top-level directory inside
    the archive is stripped so that ``dest/bin/`` contains binaries directly.
    """
    dest.mkdir(parents=True, exist_ok=True)
    print(f"  Extracting to {dest} ...", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with tarfile.open(archive) as tf:
            tf.extractall(tmp_path)
        roots = list(tmp_path.iterdir())
        src = roots[0] if strip_root and len(roots) == 1 and roots[0].is_dir() else tmp_path
        for child in src.iterdir():
            target = dest / child.name
            if target.exists():
                shutil.rmtree(target) if target.is_dir() else target.unlink()
            shutil.move(str(child), str(dest))


# ── Shim ──────────────────────────────────────────────────────────────────────


def write_shim(name: str, target: Path) -> None:
    """Write a POSIX shell shim in SHIMS_DIR that exec's *target*."""
    SHIMS_DIR.mkdir(parents=True, exist_ok=True)
    shim = SHIMS_DIR / name
    shim.write_text(f'#!/bin/sh\nexec "{target}" "$@"\n', encoding="utf-8")
    shim.chmod(0o755)


# ── Shell env file ─────────────────────────────────────────────────────────────


def write_env_file() -> None:
    """Write (or overwrite) ~/.rvn/env — a shell snippet adding rvn shims to PATH."""
    RVN_DIR.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text(
        "# rvn managed runtimes — source this in ~/.bashrc or ~/.zshrc\n"
        'export RVN_HOME="$HOME/.rvn"\n'
        'export PATH="$RVN_HOME/shims:$PATH"\n',
        encoding="utf-8",
    )
