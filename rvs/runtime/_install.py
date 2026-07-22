"""Shared helpers for downloading and extracting runtime archives."""

from __future__ import annotations

import hashlib
import platform
import shutil
import tarfile
import tempfile
from pathlib import Path

import httpx

from .. import output
from ..paths import rvs_home


# ── Directory constants ────────────────────────────────────────────────────────

RVS_DIR = rvs_home()
RUNTIMES_DIR = RVS_DIR / "runtimes"  # ~/.rvs/runtimes/{kind}/{version}/
SHIMS_DIR = RVS_DIR / "shims"  # ~/.rvs/shims/{binary} → shim scripts
ENV_FILE = RVS_DIR / "env"  # ~/.rvs/env  (source in shell rc)


# ── Platform helpers ───────────────────────────────────────────────────────────


def check_linux_x64() -> tuple[str, str]:
    """Abort if not on Linux; return (system, arch) normalised strings.

    Returns ``(system, arch)`` where ``arch`` is one of ``"x64"`` or
    ``"aarch64"``.  Calls :func:`sys.exit` on unsupported platforms.
    """
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system != "linux":
        output.fatal(f"rvs runtime management is only supported on Linux (got {system}).")
    if machine in ("x86_64", "amd64"):
        arch = "x64"
    elif machine in ("aarch64", "arm64"):
        arch = "aarch64"
    else:
        output.fatal(f"Unsupported CPU architecture: {machine}.")
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
    output.info(f"Downloading {fname} ...")
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
                if total and not output.is_json():
                    pct = downloaded * 100 // total
                    mb_done = downloaded // (1024 * 1024)
                    mb_total = total // (1024 * 1024)
                    print(f"\r  {pct:3d}%  {mb_done} / {mb_total} MB  ", end="", flush=True)
    if total and not output.is_json():
        print()  # newline after progress bar
    if digest and expected_sha256:
        actual = digest.hexdigest()
        if actual != expected_sha256:
            dest.unlink(missing_ok=True)
            output.fatal(
                f"Checksum mismatch for {fname}:\n  expected {expected_sha256}\n  got      {actual}"
            )


# ── Extract ────────────────────────────────────────────────────────────────────


def extract(archive: Path, dest: Path, *, strip_root: bool = True) -> None:
    """Extract a .tar.gz / .tar.xz archive to *dest*.

    When *strip_root* is True (default) the single top-level directory inside
    the archive is stripped so that ``dest/bin/`` contains binaries directly.
    """
    dest.mkdir(parents=True, exist_ok=True)
    output.info(f"Extracting to {dest} ...")
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


def write_shim(
    name: str,
    target: Path,
    *,
    runtime_kind: str | None = None,
    version: str | None = None,
) -> None:
    """Write a shim, resolving project pins dynamically when a kind is supplied."""
    SHIMS_DIR.mkdir(parents=True, exist_ok=True)
    shim = SHIMS_DIR / name
    if runtime_kind:
        version_arg = f' "{version}"' if version else ""
        script = (
            "#!/bin/sh\n"
            f'target="$(rvs runtime which "{runtime_kind}"{version_arg} '
            f'--executable "{name}")" || exit $?\n'
            'exec "$target" "$@"\n'
        )
    else:
        script = f'#!/bin/sh\nexec "{target}" "$@"\n'
    shim.write_text(script, encoding="utf-8")
    shim.chmod(0o755)


# ── Shell env file ─────────────────────────────────────────────────────────────


def write_env_file() -> None:
    """Write (or overwrite) ~/.rvs/env — a shell snippet adding rvs shims to PATH."""
    RVS_DIR.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text(
        "# rvs managed runtimes — source this in ~/.bashrc or ~/.zshrc\n"
        'export RVS_HOME="$HOME/.rvs"\n'
        'export PATH="$RVS_HOME/shims:$PATH"\n',
        encoding="utf-8",
    )
