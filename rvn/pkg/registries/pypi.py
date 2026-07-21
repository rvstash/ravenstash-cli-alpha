"""PyPI registry adapter.

Publish
-------
Implements the Legacy PyPI Upload API directly (same wire protocol as twine),
so no external tool is required.  The multipart form POST replicates what
``twine upload`` sends:

    POST /{customer_pid}/{repository_name}/ on the PyPI upload host
    Authorization: Basic __token__:{token}
    Content-Type: multipart/form-data

Wheel metadata parsing
----------------------
Reads the ``*.dist-info/METADATA`` file inside the wheel zip to extract
name, version, summary, etc. without importing any third-party packaging
library beyond what's already in the standard library.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from typing import TYPE_CHECKING

import httpx

from .base import PublishResult


if TYPE_CHECKING:
    from pathlib import Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_wheel_metadata(path: Path) -> dict[str, str]:
    """Extract METADATA from a .whl file, return key→value dict (first occurrence)."""
    meta: dict[str, str] = {}
    try:
        with zipfile.ZipFile(path) as zf:
            metadata_path = next(
                (n for n in zf.namelist() if n.endswith(".dist-info/METADATA")), None
            )
            if not metadata_path:
                return meta
            raw = zf.read(metadata_path).decode("utf-8", errors="replace")
        for line in raw.splitlines():
            if ": " in line:
                key, _, val = line.partition(": ")
                key_lower = key.strip().lower().replace("-", "_")
                if key_lower not in meta:
                    meta[key_lower] = val.strip()
    except Exception:
        pass
    return meta


def _read_sdist_metadata(path: Path) -> dict[str, str]:
    """Extract PKG-INFO from a .tar.gz source distribution."""
    import tarfile

    meta: dict[str, str] = {}
    try:
        with tarfile.open(path, "r:gz") as tf:
            pkg_info = next((m for m in tf.getmembers() if m.name.endswith("/PKG-INFO")), None)
            if not pkg_info:
                return meta
            f = tf.extractfile(pkg_info)
            if not f:
                return meta
            raw = f.read().decode("utf-8", errors="replace")
        for line in raw.splitlines():
            if ": " in line:
                key, _, val = line.partition(": ")
                key_lower = key.strip().lower().replace("-", "_")
                if key_lower not in meta:
                    meta[key_lower] = val.strip()
    except Exception:
        pass
    return meta


def _read_metadata(path: Path) -> dict[str, str]:
    if path.suffix == ".whl":
        return _read_wheel_metadata(path)
    if path.name.endswith(".tar.gz") or path.suffix in (".gz", ".zip", ".bz2"):
        return _read_sdist_metadata(path)
    return {}


# ── Publish ───────────────────────────────────────────────────────────────────


def publish(
    upload_url: str,
    token: str,
    files: list[Path],
    *,
    timeout: float = 120.0,
) -> list[PublishResult]:
    """Upload one or more wheel/sdist files to a PyPI-compatible registry.

    Args:
        upload_url: Full upload endpoint.
        token:      Repository token (used as HTTP Basic password).
        files:      List of paths to ``.whl`` or ``.tar.gz`` dist files.
        timeout:    Per-file upload timeout in seconds.

    Returns:
        A ``PublishResult`` for every file attempted.
    """
    results: list[PublishResult] = []

    for path in files:
        meta = _read_metadata(path)
        name = meta.get("name", path.stem)
        version = meta.get("version", "unknown")

        fields = {
            ":action": "file_upload",
            "protocol_version": "1",
            "name": name,
            "version": version,
            "filetype": "bdist_wheel" if path.suffix == ".whl" else "sdist",
            "pyversion": meta.get("requires_python", ""),
            "summary": meta.get("summary", ""),
            "sha256_digest": _sha256(path),
            "md5_digest": _md5(path),
        }

        with path.open("rb") as fh:
            file_data = fh.read()

        data = {k: v for k, v in fields.items() if v}
        files_payload = [
            ("content", (path.name, io.BytesIO(file_data), "application/octet-stream"))
        ]

        try:
            resp = httpx.post(
                upload_url,
                auth=("__token__", token),
                data=data,
                files=files_payload,
                timeout=timeout,
            )
            if resp.is_success:
                results.append(PublishResult(filename=path.name, version=version, ok=True))
            else:
                results.append(
                    PublishResult(
                        filename=path.name,
                        version=version,
                        ok=False,
                        detail=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    )
                )
        except httpx.RequestError as exc:
            results.append(
                PublishResult(filename=path.name, version=version, ok=False, detail=str(exc))
            )

    return results
