"""npm registry adapter.

Publish
-------
Implements the npm publish wire protocol directly:

1. Reads ``package.json`` from the current directory.
2. Creates a ``.tgz`` tarball (same structure as ``npm pack``).
3. Computes SHA-1 (integrity) and SHA-512 (ssri) of the tarball.
4. Builds the JSON publish body ``{ _id, name, dist-tags, versions:{...}, _attachments:{...} }``
   where the tarball is base64-encoded inside ``_attachments``.
5. PUTs the payload to ``/npm/r/{repo_id}/{package}``.

This means **no ``npm`` binary is required for publishing**.

"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path

import httpx

from .base import PublishResult


# ── Tarball helpers ───────────────────────────────────────────────────────────


def _create_tarball(package_dir: Path) -> tuple[bytes, dict]:
    """Create an npm-compatible .tgz tarball.

    Returns (tarball_bytes, package_json_dict).
    """
    pkg_json_path = package_dir / "package.json"
    if not pkg_json_path.exists():
        raise FileNotFoundError(f"package.json not found in {package_dir}")

    with pkg_json_path.open() as f:
        pkg = json.load(f)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file() and not any(
                part.startswith(".") or part == "node_modules"
                for part in path.relative_to(package_dir).parts
            ):
                arcname = f"package/{path.relative_to(package_dir)}"
                tf.add(str(path), arcname=arcname)

    return buf.getvalue(), pkg


def _shasum(data: bytes) -> str:
    """SHA-1 hex digest (npm's legacy ``shasum`` field)."""
    return hashlib.sha1(data).hexdigest()


def _integrity(data: bytes) -> str:
    """SHA-512 base64url for the ``integrity`` field (ssri format)."""
    digest = hashlib.sha512(data).digest()
    b64 = base64.b64encode(digest).decode()
    return f"sha512-{b64}"


# ── Publish ───────────────────────────────────────────────────────────────────


def publish(
    registry_url: str,
    token: str,
    package_dir: Path | None = None,
    *,
    timeout: float = 120.0,
) -> list[PublishResult]:
    """Publish the npm package in *package_dir* to *registry_url*.

    Args:
        registry_url: Base npm registry URL, e.g. ``https://host/npm/r/my-repo``.
        token:        Repository token (used as Bearer auth).
        package_dir:  Directory containing ``package.json`` (default: cwd).
        timeout:      Upload timeout in seconds.
    """
    if package_dir is None:
        package_dir = Path.cwd()

    tarball_bytes, pkg = _create_tarball(package_dir)
    name: str = pkg["name"]
    version: str = pkg["version"]
    filename = f"{name.lstrip('@').replace('/', '-')}-{version}.tgz"

    tarball_b64 = base64.b64encode(tarball_bytes).decode()
    shasum = _shasum(tarball_bytes)
    integrity = _integrity(tarball_bytes)

    # npm publish body
    safe_name = name.lstrip("@").replace("/", "-")
    tarball_url = f"{registry_url.rstrip('/')}/{name}/-/{safe_name}-{version}.tgz"

    version_manifest = {
        **pkg,
        "dist": {
            "tarball": tarball_url,
            "shasum": shasum,
            "integrity": integrity,
        },
    }

    body = {
        "_id": name,
        "name": name,
        "dist-tags": {"latest": version},
        "versions": {version: version_manifest},
        "_attachments": {
            filename: {
                "content_type": "application/octet-stream",
                "data": tarball_b64,
                "length": len(tarball_bytes),
            }
        },
    }

    # Scoped packages: PUT /@scope/pkg, unscoped: PUT /pkg
    publish_url = f"{registry_url.rstrip('/')}/{name}"

    try:
        resp = httpx.put(
            publish_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            content=json.dumps(body).encode(),
            timeout=timeout,
        )
        if resp.is_success:
            return [PublishResult(filename=filename, version=version, ok=True)]
        return [
            PublishResult(
                filename=filename,
                version=version,
                ok=False,
                detail=f"HTTP {resp.status_code}: {resp.text[:200]}",
            )
        ]
    except httpx.RequestError as exc:
        return [PublishResult(filename=filename, version=version, ok=False, detail=str(exc))]
