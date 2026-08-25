from __future__ import annotations

import io
import json
import tarfile
import zipfile
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from rvs.pkg.registries import maven as maven_reg
from rvs.pkg.registries import npm as npm_reg
from rvs.pkg.registries import pypi as pypi_reg


if TYPE_CHECKING:
    from pathlib import Path


def _mock_npm_pack(monkeypatch, included_names: tuple[str, ...]) -> None:
    def fake_pack(package_dir: Path, temp_dir: Path) -> Path:
        tarball = temp_dir / "package.tgz"
        with tarfile.open(tarball, mode="w:gz") as tf:
            for name in included_names:
                tf.add(package_dir / name, arcname=f"package/{name}")
        return tarball

    monkeypatch.setattr(npm_reg, "_npm_pack", fake_pack)


def test_pypi_publish_reads_wheel_metadata_and_posts_legacy_upload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "demo-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr(
            "demo-1.2.3.dist-info/METADATA",
            "Name: demo\nVersion: 1.2.3\nSummary: Demo package\n",
        )
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        return httpx.Response(201, text="created")

    monkeypatch.setattr(pypi_reg.httpx, "post", fake_post)

    result = pypi_reg.publish(
        upload_url="https://push.pypi.example/custpid1/repo",
        token="secret-token",
        files=[wheel],
    )

    assert result[0].ok is True
    assert result[0].filename == wheel.name
    assert result[0].version == "1.2.3"
    assert calls[0]["url"] == "https://push.pypi.example/custpid1/repo"
    assert calls[0]["auth"] == ("__token__", "secret-token")
    fields = dict(calls[0]["data"])
    assert fields["name"] == "demo"
    assert fields["version"] == "1.2.3"
    assert fields["filetype"] == "bdist_wheel"
    assert fields["pyversion"] == "py3"
    assert calls[0]["files"][0][1][0] == wheel.name


def test_pypi_publish_reports_http_failures(monkeypatch, tmp_path: Path) -> None:
    sdist = tmp_path / "demo-1.0.0.tar.gz"
    sdist.write_bytes(b"not a real sdist")
    monkeypatch.setattr(
        pypi_reg.httpx,
        "post",
        lambda url, **kwargs: httpx.Response(409, text="already exists"),
    )

    result = pypi_reg.publish(
        "https://push.pypi.example/custpid1/repo", "token", [sdist]
    )

    assert result == [
        pypi_reg.PublishResult(
            filename="demo-1.0.0.tar.gz",
            version="unknown",
            ok=False,
            detail="HTTP 409: already exists",
        )
    ]


def test_pypi_sdist_publish_uses_source_pyversion_and_requires_python(
    monkeypatch,
    tmp_path: Path,
) -> None:
    sdist = tmp_path / "demo-1.0.0.tar.gz"
    pkg_info = b"""Metadata-Version: 2.1
Name: demo
Version: 1.0.0
Requires-Python: >=3.12

Demo description
"""
    with tarfile.open(sdist, mode="w:gz") as tf:
        info = tarfile.TarInfo("demo-1.0.0/PKG-INFO")
        info.size = len(pkg_info)
        tf.addfile(info, io.BytesIO(pkg_info))
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append(kwargs)
        return httpx.Response(201, request=httpx.Request("POST", url))

    monkeypatch.setattr(pypi_reg.httpx, "post", fake_post)

    result = pypi_reg.publish("https://upload.example/repo/", "token", [sdist])

    fields = dict(calls[0]["data"])
    assert result[0].ok is True
    assert fields["pyversion"] == "source"
    assert fields["requires_python"] == ">=3.12"
    assert fields["metadata_version"] == "2.1"


def test_npm_create_tarball_uses_native_npm_packlist(monkeypatch, tmp_path: Path) -> None:
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    (package_dir / "package.json").write_text(
        '{"name": "demo", "version": "1.0.0"}',
        encoding="utf-8",
    )
    (package_dir / "index.js").write_text("module.exports = 1;\n", encoding="utf-8")
    (package_dir / ".env").write_text("SECRET=1\n", encoding="utf-8")
    node_modules = package_dir / "node_modules"
    node_modules.mkdir()
    (node_modules / "dep.js").write_text("", encoding="utf-8")
    _mock_npm_pack(monkeypatch, ("package.json", "index.js", ".env"))

    tarball, package_json = npm_reg._create_tarball(package_dir)

    assert package_json == {"name": "demo", "version": "1.0.0"}
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tf:
        names = set(tf.getnames())
    assert "package/package.json" in names
    assert "package/index.js" in names
    assert "package/.env" in names
    assert "package/node_modules/dep.js" not in names


def test_npm_publish_builds_scoped_publish_body(monkeypatch, tmp_path: Path) -> None:
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    (package_dir / "package.json").write_text(
        '{"name": "@scope/demo", "version": "1.2.3"}',
        encoding="utf-8",
    )
    (package_dir / "index.js").write_text("module.exports = 1;\n", encoding="utf-8")
    _mock_npm_pack(monkeypatch, ("package.json", "index.js"))
    calls: list[dict[str, Any]] = []

    def fake_put(url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        return httpx.Response(201, text="created", request=httpx.Request("PUT", url))

    monkeypatch.setattr(npm_reg.httpx, "put", fake_put)

    result = npm_reg.publish(
        registry_url="https://push.npm.example/custpid1/repo/",
        token="secret-token",
        package_dir=package_dir,
        download_registry_url="https://npm.example/custpid1/repo/",
    )
    body = json.loads(calls[0]["content"].decode())

    assert result[0].ok is True
    assert result[0].filename == "scope-demo-1.2.3.tgz"
    assert calls[0]["url"] == "https://push.npm.example/custpid1/repo/@scope/demo"
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-token"
    assert body["_id"] == "@scope/demo"
    assert body["dist-tags"] == {"latest": "1.2.3"}
    assert "scope-demo-1.2.3.tgz" in body["_attachments"]
    assert body["versions"]["1.2.3"]["dist"]["tarball"] == (
        "https://npm.example/custpid1/repo/@scope/demo/-/scope-demo-1.2.3.tgz"
    )


def test_maven_publish_uploads_artifact_and_checksum_sidecars(
    monkeypatch,
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "demo-1.0.0.jar"
    artifact.write_bytes(b"jar-bytes")
    calls: list[dict[str, Any]] = []

    def fake_put(url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        return httpx.Response(201, text="created", request=httpx.Request("PUT", url))

    monkeypatch.setattr(maven_reg.httpx, "put", fake_put)

    result = maven_reg.publish(
        upload_url="https://push.maven.example/custpid1/repo",
        token="secret-token",
        group_id="com.example",
        artifact_id="demo",
        version="1.0.0",
        files=[artifact],
    )

    assert result[0].ok is True
    assert result[0].filename == "demo-1.0.0.jar"
    assert [call["url"] for call in calls] == [
        "https://push.maven.example/custpid1/repo/com/example/demo/1.0.0/demo-1.0.0.jar",
        "https://push.maven.example/custpid1/repo/com/example/demo/1.0.0/demo-1.0.0.jar.md5",
        "https://push.maven.example/custpid1/repo/com/example/demo/1.0.0/demo-1.0.0.jar.sha1",
    ]
    assert calls[0]["headers"]["Authorization"] == (
        f"Basic {maven_reg._basic_auth('__token__', 'secret-token')}"
    )
    assert calls[0]["content"] == b"jar-bytes"
    assert calls[1]["content"] == maven_reg._md5(b"jar-bytes").encode()
    assert calls[2]["content"] == maven_reg._sha1(b"jar-bytes").encode()


def test_maven_publish_rejects_noncanonical_artifact_filename(tmp_path: Path) -> None:
    artifact = tmp_path / "demo.jar"
    artifact.write_bytes(b"jar")

    with pytest.raises(ValueError, match=r"demo-1\.0\.0"):
        maven_reg.publish(
            upload_url="https://upload.example/repo/",
            token="token",
            group_id="com.example",
            artifact_id="demo",
            version="1.0.0",
            files=[artifact],
        )


def test_maven_settings_xml_contains_repo_token_and_server_id() -> None:
    xml = maven_reg._build_settings_xml(
        "https://maven.example/custpid1/repo/",
        "secret-token",
        server_id="custom-server",
    )

    assert "<id>custom-server</id>" in xml
    assert "<password>secret-token</password>" in xml
    assert "<url>https://maven.example/custpid1/repo/</url>" in xml
