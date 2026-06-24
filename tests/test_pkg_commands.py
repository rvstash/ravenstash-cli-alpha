from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from rvn import config as cfg_mod
from rvn.pkg import commands as pkg_cmd
from rvn.pkg.registries.base import PublishResult
from typer.testing import CliRunner


if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()
STAGING_API_URL = "https://staging.example.test"
STAGING_HOST = "staging.example.test"


class _JsonResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeApiClient:
    def __init__(self, responses: list[Any] | None = None) -> None:
        self.responses = responses or []
        self.calls: list[tuple[str, str, Any]] = []

    def get(self, path: str, params: dict[str, Any] | None = None) -> _JsonResponse:
        self.calls.append(("GET", path, params))
        return _JsonResponse(self.responses.pop(0))

    def post(self, path: str, json: Any = None, **kwargs: Any) -> _JsonResponse:
        self.calls.append(("POST", path, json if json is not None else kwargs))
        return _JsonResponse(self.responses.pop(0) if self.responses else {})

    def delete(self, path: str) -> _JsonResponse:
        self.calls.append(("DELETE", path, None))
        return _JsonResponse(self.responses.pop(0) if self.responses else {})


def _isolate_config(monkeypatch, tmp_path: Path, content: str | None = None) -> None:
    config_dir = tmp_path / ".rvn"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text(
        content
        or """
default_profile = "default"

[profiles.default]
api_url = "https://api.ravenstash.com"
customer_id = "cus_123"
customer_public_id = "custpid1"

[profiles.staging]
customer_id = "cus_123"
customer_public_id = "custpid1"

[registries.pypi]
default_repo = "repo-pypi"

[registries.npm]
default_repo = "repo-npm"

[registries.maven]
default_repo = "repo-maven"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(cfg_mod, "PROFILE_ENV_FILE", config_dir / "profiles.env")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RVN_ENV_FILE", raising=False)
    monkeypatch.setenv("RVN_PROFILE_STAGING_API_URL", STAGING_API_URL)


def _use_fake_client(monkeypatch, fake: _FakeApiClient) -> None:
    monkeypatch.setattr(pkg_cmd.ApiClient, "from_profile", staticmethod(lambda profile=None: fake))


def test_pkg_repo_list_filters_by_kind_and_uses_profile_customer(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            [
                {
                    "id": "repo-pypi",
                    "repo_pid": "repo-pypi",
                    "registry_kind": "pypi",
                    "package_count": 2,
                    "storage_bytes": 128,
                },
                {
                    "id": "repo-npm",
                    "repo_pid": "repo-npm",
                    "registry_kind": "npm",
                    "package_count": 3,
                    "storage_bytes": 256,
                },
            ]
        ]
    )
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(pkg_cmd.app, ["repo", "list", "--kind", "pypi"])

    assert result.exit_code == 0
    assert fake.calls == [("GET", "/webapp/repository/", {"customer_id": "cus_123"})]
    assert "repo-pypi" in result.output
    assert "repo-npm" not in result.output


def test_pkg_repo_create_can_set_default_repo(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient([{"id": "new-node", "repo_pid": "new-node"}])
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(
        pkg_cmd.app, ["repo", "create", "new-node", "--kind", "npm", "--default"]
    )

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "POST",
            "/webapp/repository/",
            {
                "customer_id": "cus_123",
                "repo_pid": "new-node",
                "registry_kind": "npm",
            },
        )
    ]
    assert cfg_mod.load().registry_defaults("npm").default_repo == "new-node"
    assert "Created npm package repository" in result.output


def test_pkg_repo_create_rejects_unknown_kind(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)

    result = runner.invoke(pkg_cmd.app, ["repo", "create", "bad", "--kind", "gem"])

    assert result.exit_code == 1
    assert "Unknown package repository kind 'gem'" in result.stderr


def test_pkg_repo_show_renders_repository_details(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            {
                "id": "repo-pypi",
                "repo_pid": "repo-pypi",
                "registry_kind": "pypi",
                "package_count": 7,
                "storage_bytes": 4096,
                "created_at": "2026-06-20T00:00:00Z",
            }
        ]
    )
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(pkg_cmd.app, ["repo", "show", "repo-pypi"])

    assert result.exit_code == 0
    assert fake.calls == [("GET", "/webapp/repository/repo-pypi", None)]
    assert "repo-pypi" in result.output
    assert "4096" in result.output


def test_pkg_package_list_and_show_use_repository_package_paths(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            {
                "items": [
                    {
                        "package_name": "demo",
                        "latest_version": "1.2.3",
                        "version_count": 2,
                        "total_size_bytes": 1234,
                    }
                ]
            },
            {
                "repository_id": "repo-pypi",
                "package_name": "demo",
                "latest_version": "1.2.3",
                "version_count": 2,
                "total_size_bytes": 1234,
                "versions": [
                    {
                        "version": "1.2.3",
                        "yanked": False,
                        "files": [{"filename": "demo.whl"}],
                        "total_size_bytes": 1000,
                    }
                ],
            },
        ]
    )
    _use_fake_client(monkeypatch, fake)

    list_result = runner.invoke(pkg_cmd.app, ["package", "list", "--repo", "repo-pypi"])
    show_result = runner.invoke(pkg_cmd.app, ["package", "show", "demo", "--repo", "repo-pypi"])

    assert list_result.exit_code == 0
    assert show_result.exit_code == 0
    assert fake.calls == [
        ("GET", "/webapp/repository/repo-pypi/packages", None),
        ("GET", "/webapp/repository/repo-pypi/packages/demo", None),
    ]
    assert "demo" in list_result.output
    assert "1.2.3" in show_result.output


def test_pkg_package_mutations_call_expected_api_paths(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient()
    _use_fake_client(monkeypatch, fake)

    delete_result = runner.invoke(
        pkg_cmd.app,
        ["package", "delete", "demo", "--repo", "repo-pypi", "--yes"],
    )
    delete_version_result = runner.invoke(
        pkg_cmd.app,
        ["package", "delete-version", "demo", "1.0.0", "--repo", "repo-pypi", "--yes"],
    )
    yank_result = runner.invoke(
        pkg_cmd.app,
        ["package", "yank", "demo", "1.0.1", "--repo", "repo-pypi", "--reason", "bad build"],
    )

    assert delete_result.exit_code == 0
    assert delete_version_result.exit_code == 0
    assert yank_result.exit_code == 0
    assert fake.calls == [
        ("DELETE", "/webapp/repository/repo-pypi/packages/demo", None),
        ("DELETE", "/webapp/repository/repo-pypi/packages/demo/versions/1.0.0", None),
        (
            "POST",
            "/webapp/repository/repo-pypi/packages/demo/versions/1.0.1/yank",
            {"reason": "bad build"},
        ),
    ]


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            ["pypi", "index-url", "--profile", "staging"],
            f"{STAGING_API_URL}/pypi/x/custpid1/repo-pypi/simple/",
        ),
        (
            ["pypi", "upload-url", "--profile", "staging"],
            f"{STAGING_API_URL}/native/pypi/x/custpid1/repo-pypi/",
        ),
        (
            ["npm", "registry-url", "--profile", "staging"],
            f"{STAGING_API_URL}/npm/x/custpid1/repo-npm/",
        ),
        (
            ["maven", "repo-url", "--profile", "staging"],
            f"{STAGING_API_URL}/maven/x/custpid1/repo-maven/",
        ),
    ],
)
def test_pkg_registry_url_helpers_use_profile_and_default_repo(
    monkeypatch,
    tmp_path: Path,
    args: list[str],
    expected: str,
) -> None:
    _isolate_config(monkeypatch, tmp_path)

    result = runner.invoke(pkg_cmd.app, args)

    assert result.exit_code == 0
    assert result.output.strip() == expected


def test_pkg_configure_snippets_are_printed_for_native_toolchains(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)

    pypi_result = runner.invoke(pkg_cmd.app, ["pypi", "configure", "--profile", "staging"])
    npm_result = runner.invoke(pkg_cmd.app, ["npm", "configure", "--profile", "staging"])
    maven_result = runner.invoke(pkg_cmd.app, ["maven", "configure", "--profile", "staging"])

    assert pypi_result.exit_code == 0
    assert "extra-index-url" in pypi_result.output
    assert "repo-pypi" in pypi_result.output
    assert npm_result.exit_code == 0
    assert "_authToken=${RVN_TOKEN}" in npm_result.output
    assert "repo-npm" in npm_result.output
    assert maven_result.exit_code == 0
    assert "<settings" in maven_result.output
    assert "repo-maven" in maven_result.output


def test_pypi_install_injects_authenticated_extra_index_url(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVN_TOKEN", "secret-token")
    monkeypatch.setattr(pkg_cmd.tools, "pip_cmd", lambda: ["/bin/pip"])
    calls: list[tuple[list[str], dict[str, str]]] = []
    monkeypatch.setattr(
        pkg_cmd.subprocess,
        "run",
        lambda cmd, *, env, check: calls.append((cmd, env)),
    )

    result = runner.invoke(pkg_cmd.app, ["pypi", "install", "demo", "--profile", "staging"])

    assert result.exit_code == 0
    assert calls[0][0] == ["/bin/pip", "install", "demo"]
    assert calls[0][1]["PIP_EXTRA_INDEX_URL"] == (
        f"https://__token__:secret-token@{STAGING_HOST}/pypi/x/custpid1/repo-pypi/simple/"
    )


def test_npm_install_injects_token_for_registry_host(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVN_TOKEN", "secret-token")
    monkeypatch.setattr(pkg_cmd.tools, "npm", lambda: "/bin/npm")
    calls: list[tuple[list[str], dict[str, str]]] = []
    monkeypatch.setattr(
        pkg_cmd.subprocess,
        "run",
        lambda cmd, *, env, check: calls.append((cmd, env)),
    )

    result = runner.invoke(pkg_cmd.app, ["npm", "install", "@scope/demo", "--profile", "staging"])

    assert result.exit_code == 0
    assert calls[0][0] == [
        "/bin/npm",
        "install",
        "--registry",
        f"{STAGING_API_URL}/npm/x/custpid1/repo-npm/",
        "@scope/demo",
    ]
    assert (
        calls[0][1][f"NPM_CONFIG_//{STAGING_HOST}/npm/x/custpid1/repo-npm/:_authToken"]
        == "secret-token"
    )


def test_pypi_publish_reports_failed_uploads(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVN_TOKEN", "secret-token")
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "demo-1.0.0.whl").write_bytes(b"wheel")
    monkeypatch.setattr(
        pkg_cmd.pypi_reg,
        "publish",
        lambda **kwargs: [
            PublishResult("demo-1.0.0.whl", "1.0.0", True),
            PublishResult("demo-1.0.0.tar.gz", "1.0.0", False, "HTTP 500"),
        ],
    )

    result = runner.invoke(pkg_cmd.app, ["pypi", "publish", str(dist_dir), "--profile", "staging"])

    assert result.exit_code == 1
    assert "Published demo-1.0.0.whl" in result.output
    assert "Failed demo-1.0.0.tar.gz" in result.stderr


def test_npm_publish_calls_registry_adapter(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVN_TOKEN", "secret-token")
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    calls: list[dict[str, Any]] = []

    def fake_publish(**kwargs: Any) -> list[PublishResult]:
        calls.append(kwargs)
        return [PublishResult("demo-1.0.0.tgz", "1.0.0", True)]

    monkeypatch.setattr(pkg_cmd.npm_reg, "publish", fake_publish)

    result = runner.invoke(
        pkg_cmd.app, ["npm", "publish", str(package_dir), "--profile", "staging"]
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "registry_url": f"{STAGING_API_URL}/native/npm/x/custpid1/repo-npm/",
            "token": "secret-token",
            "package_dir": package_dir,
            "download_registry_url": f"{STAGING_API_URL}/npm/x/custpid1/repo-npm/",
        }
    ]


def test_maven_deploy_checks_file_and_calls_registry_adapter(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVN_TOKEN", "secret-token")
    artifact = tmp_path / "demo.jar"
    artifact.write_bytes(b"jar")
    calls: list[dict[str, Any]] = []

    def fake_publish(**kwargs: Any) -> list[PublishResult]:
        calls.append(kwargs)
        return [PublishResult("demo.jar", "1.0.0", True)]

    monkeypatch.setattr(pkg_cmd.maven_reg, "publish", fake_publish)

    result = runner.invoke(
        pkg_cmd.app,
        [
            "maven",
            "deploy",
            str(artifact),
            "--group",
            "com.example",
            "--artifact",
            "demo",
            "--version",
            "1.0.0",
            "--profile",
            "staging",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "upload_url": f"{STAGING_API_URL}/native/maven/x/custpid1/repo-maven/",
            "token": "secret-token",
            "group_id": "com.example",
            "artifact_id": "demo",
            "version": "1.0.0",
            "files": [artifact],
        }
    ]
