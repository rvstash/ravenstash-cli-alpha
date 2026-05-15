"""Maven registry adapter.

Publish
-------
Maven artifacts are uploaded as individual HTTP PUTs.  For each file (JAR,
POM, sources JAR, etc.) we:

1. Compute the Maven repository path:
   ``{group_path}/{artifact_id}/{version}/{artifact_id}-{version}.jar``
2. PUT the file to ``/maven/r/{repo_pid}/{path}``
3. PUT the MD5 and SHA-1 checksum sidecar files.

For multi-module projects, delegates to ``mvn deploy:deploy-file`` with a
generated temporary ``settings.xml`` that injects the private registry URL
and token-based auth.

Install (fetch)
---------------
Delegates to ``mvn dependency:get`` with a generated ``settings.xml``.
For Gradle projects, delegates to ``gradle dependencies`` with a generated
``build.gradle`` snippet (future work — stub provided).

Coordinates format
------------------
Maven GAV: ``groupId:artifactId:version`` (e.g. ``com.example:mylib:1.2.3``).
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
import textwrap
from pathlib import Path

import httpx

from .base import PublishResult


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
        upload_url:   Base upload URL, e.g. ``https://host/maven/r/my-repo``.
        token:        Repository token (HTTP Basic password).
        group_id:     Maven groupId, e.g. ``com.example``.
        artifact_id:  Maven artifactId, e.g. ``mylib``.
        version:      Version string, e.g. ``1.2.3``.
        files:        Local artifact files to upload (JAR, POM, etc.).
        timeout:      Per-file upload timeout in seconds.
    """
    results: list[PublishResult] = []

    for path in files:
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


def _build_settings_xml(repo_url: str, token: str, server_id: str = "rvn-private") -> str:
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
              <id>rvn</id>
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
            <activeProfile>rvn</activeProfile>
          </activeProfiles>
        </settings>
    """)


# ── Install (fetch) ───────────────────────────────────────────────────────────


def install(
    repo_url: str,
    token: str,
    coords: str,
    *,
    extra_args: list[str] | None = None,
) -> None:
    """Fetch a Maven artifact using ``mvn dependency:get``.

    Args:
        repo_url:   Maven repository URL, e.g. ``https://host/maven/r/my-repo``.
        token:      Repository token.
        coords:     Maven GAV coordinates, e.g. ``com.example:mylib:1.2.3``.
        extra_args: Additional args forwarded to ``mvn``.
    """
    xml = _build_settings_xml(repo_url, token)
    with tempfile.NamedTemporaryFile(suffix=".xml", mode="w", delete=False) as f:
        f.write(xml)
        settings_path = f.name

    try:
        cmd = [
            "mvn",
            f"--settings={settings_path}",
            "dependency:get",
            f"-Dartifact={coords}",
            f"-DremoteRepositories=rvn-private:::::{repo_url}",
        ]
        if extra_args:
            cmd.extend(extra_args)
        subprocess.run(cmd, check=True)
    finally:
        Path(settings_path).unlink(missing_ok=True)


# ── deploy:deploy-file delegation ────────────────────────────────────────────


def deploy_file(
    repo_url: str,
    token: str,
    group_id: str,
    artifact_id: str,
    version: str,
    jar: Path,
    pom: Path | None = None,
    *,
    extra_args: list[str] | None = None,
) -> None:
    """Deploy a file via ``mvn deploy:deploy-file`` (useful for complex builds).

    This is an alternative to the direct HTTP PUT path and useful when the
    caller already has Maven installed and wants Maven to handle checksum
    generation and retries.
    """
    xml = _build_settings_xml(repo_url, token)
    with tempfile.NamedTemporaryFile(suffix=".xml", mode="w", delete=False) as f:
        f.write(xml)
        settings_path = f.name

    try:
        cmd = [
            "mvn",
            f"--settings={settings_path}",
            "deploy:deploy-file",
            f"-Durl={repo_url}",
            "-DrepositoryId=rvn-private",
            f"-DgroupId={group_id}",
            f"-DartifactId={artifact_id}",
            f"-Dversion={version}",
            f"-Dfile={jar}",
        ]
        if pom:
            cmd.append(f"-DpomFile={pom}")
        if extra_args:
            cmd.extend(extra_args)
        subprocess.run(cmd, check=True)
    finally:
        Path(settings_path).unlink(missing_ok=True)


# ── Registry URL helper ───────────────────────────────────────────────────────


def repo_url(api_url: str, repo_slug: str) -> str:
    return f"{api_url.rstrip('/')}/maven/r/{repo_slug}"
