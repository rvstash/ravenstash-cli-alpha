from __future__ import annotations

import io
import json
import tarfile
import zipfile
from typing import TYPE_CHECKING, Any

import httpx
from rvn.pkg.registries import maven as maven_reg
from rvn.pkg.registries import npm as npm_reg
from rvn.pkg.registries import pypi as pypi_reg


if TYPE_CHECKING:
    from pathlib import Path


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
        upload_url="https://api.example/native/pypi/x/custpid1/repo",
        token="secret-token",
        files=[wheel],
    )

    assert result[0].ok is True
    assert result[0].filename == wheel.name
    assert result[0].version == "1.2.3"
    assert calls[0]["url"] == "https://api.example/native/pypi/x/custpid1/repo"
    assert calls[0]["auth"] == ("__token__", "secret-token")
    assert calls[0]["data"]["name"] == "demo"
    assert calls[0]["data"]["version"] == "1.2.3"
    assert calls[0]["data"]["filetype"] == "bdist_wheel"
    assert calls[0]["files"][0][1][0] == wheel.name


def test_pypi_publish_reports_http_failures(monkeypatch, tmp_path: Path) -> None:
    sdist = tmp_path / "demo-1.0.0.tar.gz"
    sdist.write_bytes(b"not a real sdist")
    monkeypatch.setattr(
        pypi_reg.httpx,
        "post",
        lambda url, **kwargs: httpx.Response(409, text="already exists"),
    )

    result = pypi_reg.publish("https://api.example/native/pypi/x/custpid1/repo", "token", [sdist])

    assert result == [
        pypi_reg.PublishResult(
            filename="demo-1.0.0.tar.gz",
            version="unknown",
            ok=False,
            detail="HTTP 409: already exists",
        )
    ]


def test_npm_create_tarball_excludes_dotfiles_and_node_modules(tmp_path: Path) -> None:
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

    tarball, package_json = npm_reg._create_tarball(package_dir)

    assert package_json == {"name": "demo", "version": "1.0.0"}
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tf:
        names = set(tf.getnames())
    assert "package/package.json" in names
    assert "package/index.js" in names
    assert "package/.env" not in names
    assert "package/node_modules/dep.js" not in names


def test_npm_publish_builds_scoped_publish_body(monkeypatch, tmp_path: Path) -> None:
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    (package_dir / "package.json").write_text(
        '{"name": "@scope/demo", "version": "1.2.3"}',
        encoding="utf-8",
    )
    (package_dir / "index.js").write_text("module.exports = 1;\n", encoding="utf-8")
    calls: list[dict[str, Any]] = []

    def fake_put(url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        return httpx.Response(201, text="created", request=httpx.Request("PUT", url))

    monkeypatch.setattr(npm_reg.httpx, "put", fake_put)

    result = npm_reg.publish(
        registry_url="https://api.example/native/npm/x/custpid1/repo/",
        token="secret-token",
        package_dir=package_dir,
        download_registry_url="https://api.example/npm/x/custpid1/repo/",
    )
    body = json.loads(calls[0]["content"].decode())

    assert result[0].ok is True
    assert result[0].filename == "scope-demo-1.2.3.tgz"
    assert calls[0]["url"] == "https://api.example/native/npm/x/custpid1/repo/@scope/demo"
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-token"
    assert body["_id"] == "@scope/demo"
    assert body["dist-tags"] == {"latest": "1.2.3"}
    assert "scope-demo-1.2.3.tgz" in body["_attachments"]
    assert body["versions"]["1.2.3"]["dist"]["tarball"] == (
        "https://api.example/npm/x/custpid1/repo/@scope/demo/-/scope-demo-1.2.3.tgz"
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
        upload_url="https://api.example/native/maven/x/custpid1/repo",
        token="secret-token",
        group_id="com.example",
        artifact_id="demo",
        version="1.0.0",
        files=[artifact],
    )

    assert result[0].ok is True
    assert result[0].filename == "demo-1.0.0.jar"
    assert [call["url"] for call in calls] == [
        "https://api.example/native/maven/x/custpid1/repo/com/example/demo/1.0.0/demo-1.0.0.jar",
        "https://api.example/native/maven/x/custpid1/repo/com/example/demo/1.0.0/demo-1.0.0.jar.md5",
        "https://api.example/native/maven/x/custpid1/repo/com/example/demo/1.0.0/demo-1.0.0.jar.sha1",
    ]
    assert calls[0]["headers"]["Authorization"] == (
        f"Basic {maven_reg._basic_auth('__token__', 'secret-token')}"
    )
    assert calls[0]["content"] == b"jar-bytes"
    assert calls[1]["content"] == maven_reg._md5(b"jar-bytes").encode()
    assert calls[2]["content"] == maven_reg._sha1(b"jar-bytes").encode()


def test_maven_settings_xml_contains_repo_token_and_server_id() -> None:
    xml = maven_reg._build_settings_xml(
        "https://api.example/maven/x/custpid1/repo/",
        "secret-token",
        server_id="custom-server",
    )

    assert "<id>custom-server</id>" in xml
    assert "<password>secret-token</password>" in xml
    assert "<url>https://api.example/maven/x/custpid1/repo/</url>" in xml
