"""PyPI registry adapter.

Publish
-------
Implements the Legacy PyPI Upload API directly (same wire protocol as twine),
so no external tool is required.  The multipart form POST replicates what
``twine upload`` sends:

    POST /{namespace_unique_ref}/{repository_unique_ref}/ on the PyPI push host
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
from email.parser import Parser
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


def _parse_metadata(raw: str) -> dict[str, str | list[str]]:
    message = Parser().parsestr(raw)
    meta: dict[str, str | list[str]] = {}
    multi_headers = {
        "classifier": "classifiers",
        "requires-dist": "requires_dist",
        "provides-extra": "provides_extra",
        "project-url": "project_urls",
    }
    for header, field in multi_headers.items():
        values = [value.strip() for value in message.get_all(header, []) if value.strip()]
        if values:
            meta[field] = values
    single_headers = {
        "Name": "name",
        "Version": "version",
        "Metadata-Version": "metadata_version",
        "Summary": "summary",
        "Home-Page": "home_page",
        "Requires-Python": "requires_python",
        "Author": "author",
        "Author-email": "author_email",
        "Maintainer": "maintainer",
        "Maintainer-email": "maintainer_email",
        "License": "license",
        "Keywords": "keywords",
        "Platform": "platform",
        "Download-URL": "download_url",
        "Description-Content-Type": "description_content_type",
    }
    for header, field in single_headers.items():
        value = message.get(header)
        if value:
            meta[field] = value.strip()
    description = message.get_payload()
    if isinstance(description, str) and description.strip():
        meta["description"] = description.strip()
    return meta


def _read_wheel_metadata(path: Path) -> dict[str, str | list[str]]:
    """Extract Core Metadata fields from a wheel."""
    try:
        with zipfile.ZipFile(path) as zf:
            metadata_path = next(
                (n for n in zf.namelist() if n.endswith(".dist-info/METADATA")), None
            )
            if not metadata_path:
                return {}
            raw = zf.read(metadata_path).decode("utf-8", errors="replace")
        return _parse_metadata(raw)
    except Exception:
        return {}


def _read_sdist_metadata(path: Path) -> dict[str, str | list[str]]:
    """Extract PKG-INFO from a .tar.gz source distribution."""
    import tarfile

    try:
        with tarfile.open(path, "r:gz") as tf:
            pkg_info = next((m for m in tf.getmembers() if m.name.endswith("/PKG-INFO")), None)
            if not pkg_info:
                return {}
            f = tf.extractfile(pkg_info)
            if not f:
                return {}
            raw = f.read().decode("utf-8", errors="replace")
        return _parse_metadata(raw)
    except Exception:
        return {}


def _read_metadata(path: Path) -> dict[str, str | list[str]]:
    if path.suffix == ".whl":
        return _read_wheel_metadata(path)
    if path.name.endswith(".tar.gz") or path.suffix in (".gz", ".zip", ".bz2"):
        return _read_sdist_metadata(path)
    return {}


def _metadata_text(meta: dict[str, str | list[str]], field: str, default: str = "") -> str:
    value = meta.get(field, default)
    return value if isinstance(value, str) else default


def _wheel_python_tag(path: Path) -> str:
    stem = path.name.removesuffix(".whl")
    parts = stem.rsplit("-", 3)
    return parts[-3] if len(parts) == 4 and parts[-3] else "py3"


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
        name = _metadata_text(meta, "name", path.stem)
        version = _metadata_text(meta, "version", "unknown")
        is_wheel = path.suffix == ".whl"

        fields = {
            ":action": "file_upload",
            "protocol_version": "1",
            "name": name,
            "version": version,
            "filetype": "bdist_wheel" if is_wheel else "sdist",
            "pyversion": _wheel_python_tag(path) if is_wheel else "source",
            "sha256_digest": _sha256(path),
            "md5_digest": _md5(path),
        }
        for field in (
            "metadata_version",
            "summary",
            "home_page",
            "requires_python",
            "author",
            "author_email",
            "maintainer",
            "maintainer_email",
            "license",
            "description",
            "keywords",
            "platform",
            "download_url",
            "description_content_type",
        ):
            value = _metadata_text(meta, field)
            if value:
                fields[field] = value

        with path.open("rb") as fh:
            file_data = fh.read()

        data: dict[str, str | list[str]] = dict(fields)
        for field in ("classifiers", "requires_dist", "provides_extra", "project_urls"):
            values = meta.get(field, [])
            if isinstance(values, list):
                data[field] = values
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
