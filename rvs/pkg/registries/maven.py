"""Maven registry adapter.

Publish
-------
Maven artifacts are uploaded as individual HTTP PUTs.  For each file (JAR,
POM, sources JAR, etc.) we:

1. Compute the Maven repository path:
   ``{group_path}/{artifact_id}/{version}/{artifact_id}-{version}.jar``
2. PUT the file to ``/{workspace_unique_ref}/{repository_unique_ref}/{path}`` on the Maven push host
3. PUT the MD5 and SHA-1 checksum sidecar files.

Coordinates format
------------------
Maven GAV: ``groupId:artifactId:version`` (e.g. ``com.example:mylib:1.2.3``).
"""

from __future__ import annotations

import hashlib
import re
import textwrap
from typing import TYPE_CHECKING

import httpx

from .base import PublishResult


if TYPE_CHECKING:
    from pathlib import Path


# ── Checksum helpers ──────────────────────────────────────────────────────────


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


# ── Maven path helpers ────────────────────────────────────────────────────────


def _group_path(group_id: str) -> str:
    return group_id.replace(".", "/")


def artifact_path(group_id: str, artifact_id: str, version: str, filename: str) -> str:
    return f"{_group_path(group_id)}/{artifact_id}/{version}/{filename}"


_ARTIFACT_EXTENSION_RE = re.compile(
    r"\.(?:jar|aar|war|ear|pom|module|zip|tar\.gz|apk|klib|hpi|jpi|nbm|gradle)$"
)


def validate_artifact_filename(filename: str, artifact_id: str, version: str) -> None:
    """Reject filenames that Maven clients cannot resolve from the coordinates."""
    if not _ARTIFACT_EXTENSION_RE.search(filename):
        raise ValueError(f"Unsupported Maven artifact filename: {filename}")
    stem = _ARTIFACT_EXTENSION_RE.sub("", filename)
    expected = f"{artifact_id}-{version}"
    if stem == expected or stem.startswith(f"{expected}-"):
        return
    if version.upper().endswith("-SNAPSHOT"):
        snapshot_base = f"{artifact_id}-{version[:-9]}"
        if re.match(
            rf"^{re.escape(snapshot_base)}-\d{{8}}\.\d{{6}}-\d+(?:-.+)?$",
            stem,
        ):
            return
    raise ValueError(
        f"Maven artifact filename '{filename}' must match "
        f"'{artifact_id}-{version}[-classifier].<extension>'."
    )


def _put_file(upload_base: str, token: str, path: str, data: bytes, timeout: float) -> None:
    url = f"{upload_base.rstrip('/')}/{path.lstrip('/')}"
    resp = httpx.put(
        url,
        content=data,
        headers={
            "Authorization": f"Basic {_basic_auth('__token__', token)}",
            "Content-Type": "application/octet-stream",
        },
        timeout=timeout,
    )
    resp.raise_for_status()


def _basic_auth(user: str, password: str) -> str:
    import base64

    return base64.b64encode(f"{user}:{password}".encode()).decode()


# ── Publish ───────────────────────────────────────────────────────────────────


def publish(
    upload_url: str,
    token: str,
    group_id: str,
    artifact_id: str,
    version: str,
    files: list[Path],
    *,
    timeout: float = 120.0,
) -> list[PublishResult]:
    """Upload Maven artifacts by direct HTTP PUT.

    Args:
        upload_url:   Base upload URL.
        token:        Repository token (HTTP Basic password).
        group_id:     Maven groupId, e.g. ``com.example``.
        artifact_id:  Maven artifactId, e.g. ``mylib``.
        version:      Version string, e.g. ``1.2.3``.
        files:        Local artifact files to upload (JAR, POM, etc.).
        timeout:      Per-file upload timeout in seconds.
    """
    results: list[PublishResult] = []

    for path in files:
        validate_artifact_filename(path.name, artifact_id, version)
        file_data = path.read_bytes()
        remote_path = artifact_path(group_id, artifact_id, version, path.name)
        try:
            _put_file(upload_url, token, remote_path, file_data, timeout)
            # Upload MD5 and SHA-1 checksums as sidecar files
            _put_file(upload_url, token, remote_path + ".md5", _md5(file_data).encode(), timeout)
            _put_file(upload_url, token, remote_path + ".sha1", _sha1(file_data).encode(), timeout)
            results.append(PublishResult(filename=path.name, version=version, ok=True))
        except httpx.HTTPStatusError as exc:
            results.append(
                PublishResult(
                    filename=path.name,
                    version=version,
                    ok=False,
                    detail=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                )
            )
        except httpx.RequestError as exc:
            results.append(
                PublishResult(filename=path.name, version=version, ok=False, detail=str(exc))
            )

    return results


# ── settings.xml generation ───────────────────────────────────────────────────


def _build_settings_xml(repo_url: str, token: str, server_id: str = "rvs-private") -> str:
    """Generate a minimal Maven settings.xml for the private registry."""
    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <settings xmlns="http://maven.apache.org/SETTINGS/1.0.0">
          <servers>
            <server>
              <id>{server_id}</id>
              <username>__token__</username>
              <password>{token}</password>
            </server>
          </servers>
          <profiles>
            <profile>
              <id>rvs</id>
              <repositories>
                <repository>
                  <id>{server_id}</id>
                  <url>{repo_url}</url>
                  <releases><enabled>true</enabled></releases>
                  <snapshots><enabled>true</enabled></snapshots>
                </repository>
              </repositories>
            </profile>
          </profiles>
          <activeProfiles>
            <activeProfile>rvs</activeProfile>
          </activeProfiles>
        </settings>
    """)
