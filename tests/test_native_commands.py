from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rvs import config as cfg_mod
from rvs.cli import app
from rvs.native import runner as native_runner
from typer.testing import CliRunner


if TYPE_CHECKING:
    from collections.abc import Callable


runner = CliRunner()
STAGING_API_URL = "https://staging.example.test"
STAGING_DOWNLOAD_URL = "https://pkg-staging.example.test"
STAGING_DOWNLOAD_HOST = "pkg-staging.example.test"
STAGING_UPLOAD_URL = "https://push-staging.example.test"
STAGING_UPLOAD_HOST = "push-staging.example.test"


class _Completed:
    returncode = 0


class _JsonResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def json(self) -> dict[str, Any]:
        return self.payload


class _FakeDevApi:
    def get(self, path: str, params=None) -> _JsonResponse:
        assert path == "/v0/repositories/resolve"
        return _JsonResponse(
            {
                "customer": {
                    "customer_id": "cus_staging",
                    "customer_unique_ref": "_custpid1",
                },
                "repository": {
                    "id": "repository-1",
                    "repository_name": "repo",
                    "workspace_id": "workspace-1",
                    "workspace_unique_ref": "_abcdefgh",
                    "workspace_name": "staging",
                    "repository_unique_ref": "_xyzabcde",
                },
            }
        )

    def post(self, path: str, json=None) -> _JsonResponse:
        assert path == "/v0/package-credentials"
        return _JsonResponse({"access_token": "secret-token"})


def _isolate_config(monkeypatch: Any, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvs"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text(
        f"""
default_profile = "staging"

[profiles.staging]
api_url = "{STAGING_API_URL}"
pkg_download_url = "{STAGING_DOWNLOAD_URL}"
pkg_upload_url = "{STAGING_UPLOAD_URL}"
customer_id = "cus_staging"
customer_unique_id = "custpid1"

[profiles.staging.registries.pypi]
default_repo = "_abcdefgh/_xyzabcde"

[profiles.staging.registries.npm]
default_repo = "_abcdefgh/_xyzabcde"

[profiles.staging.registries.maven]
default_repo = "_abcdefgh/_xyzabcde"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(cfg_mod, "PROFILE_ENV_FILE", config_dir / "profiles.env")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RVS_TOKEN", "secret-token")
    monkeypatch.setattr(
        native_runner.ApiClient,
        "from_profile",
        staticmethod(lambda profile=None: _FakeDevApi()),
    )


def _mock_native_tools(monkeypatch: Any) -> None:
    monkeypatch.setattr(native_runner.tools, "pip_cmd", lambda: ["/bin/pip"])
    monkeypatch.setattr(native_runner.tools, "npm", lambda: "/bin/npm")
    monkeypatch.setattr(
        native_runner.tools,
        "require",
        lambda name, *, install_kind: f"/bin/{name}",
    )


def _capture_run(
    monkeypatch: Any,
    calls: list[dict[str, Any]],
    hook: Callable[[list[str], dict[str, str]], None] | None = None,
) -> None:
    def fake_run(cmd: list[str], *, env: dict[str, str], check: bool) -> _Completed:
        del check
        if hook:
            hook(cmd, env)
        calls.append({"cmd": cmd, "env": env.copy()})
        return _Completed()

    monkeypatch.setattr(native_runner.subprocess, "run", fake_run)


def test_ravenstash_url_kind_accepts_public_hosts_and_local_normalized_routes() -> None:
    assert (
        native_runner._ravenstash_url_kind(
            "https://npm.pkg-staging.example.test/x/_abcdefgh/_xyzabcde/"
        )
        == "npm"
    )
    assert (
        native_runner._ravenstash_url_kind(
            "https://pypi.pkg-staging.example.test/x/_abcdefgh/_xyzabcde/simple/"
        )
        == "pypi"
    )
    assert (
        native_runner._ravenstash_url_kind(
            "http://localhost:8788/native/maven/x/_abcdefgh/_xyzabcde/com/example/demo/"
        )
        == "maven"
    )
    assert (
        native_runner._ravenstash_url_kind(
            "http://localhost:8788/native/pypi/r/_abcdefgh/piwheels/simple/"
        )
        == "pypi"
    )
    assert (
        native_runner._ravenstash_url_kind(
            "https://pypi.pkg-staging.example.test/r/o/pypiorg/simple/"
        )
        == "pypi"
    )
    assert (
        native_runner._ravenstash_url_kind(
            "https://npm.pkg-staging.example.test/r/_abcdefgh/_xyzabcde/"
        )
        == "npm"
    )
    assert (
        native_runner._ravenstash_url_kind("https://npm.example.test/x/_abcdefgh/_xyzabcde/")
        is None
    )
    assert (
        native_runner._ravenstash_url_kind(
            "https://pkg-staging.example.test/x/_abcdefgh/_xyzabcde/"
        )
        is None
    )
    assert (
        native_runner._ravenstash_url_kind("http://localhost:8788/native/npm/x/_abcdefgh/") is None
    )
    assert (
        native_runner._ravenstash_url_kind("https://npm.pkg-staging.example.test/x/_abcdefgh/")
        is None
    )
    assert (
        native_runner._ravenstash_url_kind(
            "https://pypi.pkg-staging.example.test/r/_abcdefgh/"
        )
        is None
    )


def test_native_npm_respects_project_npmrc_and_injects_path_scoped_auth(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    (tmp_path / ".npmrc").write_text(
        f"@acme:registry=https://npm.{STAGING_DOWNLOAD_HOST}/x/_abcdefgh/_xyzabcde/\n",
        encoding="utf-8",
    )
    calls: list[dict[str, Any]] = []
    _capture_run(monkeypatch, calls)

    result = runner.invoke(app, ["npm", "install", "@acme/widgets"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == ["/bin/npm", "install", "@acme/widgets"]
    assert "NPM_CONFIG_REGISTRY" not in calls[0]["env"]
    assert (
        calls[0]["env"][
            f"NPM_CONFIG_//npm.{STAGING_DOWNLOAD_HOST}/x/_abcdefgh/_xyzabcde/:_authToken"
        ]
        == "secret-token"
    )


def test_native_npm_repo_override_uses_upload_registry_for_publish(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    calls: list[dict[str, Any]] = []
    _capture_run(monkeypatch, calls)

    result = runner.invoke(app, ["npm", "--rvs-repo", "repo-npm", "publish"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == [
        "/bin/npm",
        "publish",
        "--registry",
        f"https://npm.{STAGING_UPLOAD_HOST}/x/_abcdefgh/_xyzabcde/",
    ]
    assert calls[0]["env"]["NPM_CONFIG_REGISTRY"] == (
        f"https://npm.{STAGING_UPLOAD_HOST}/x/_abcdefgh/_xyzabcde/"
    )
    assert (
        calls[0]["env"][f"NPM_CONFIG_//npm.{STAGING_UPLOAD_HOST}/x/_abcdefgh/_xyzabcde/:_authToken"]
        == "secret-token"
    )


def test_native_npm_repo_override_replaces_conflicting_registry_flag(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    calls: list[dict[str, Any]] = []
    _capture_run(monkeypatch, calls)

    result = runner.invoke(
        app,
        [
            "npm",
            "--rvs-repo",
            "repo-npm",
            "install",
            "--registry",
            "https://registry.npmjs.org/",
            "@acme/widgets",
        ],
    )

    assert result.exit_code == 0
    assert calls[0]["cmd"] == [
        "/bin/npm",
        "install",
        "--registry",
        f"https://npm.{STAGING_DOWNLOAD_HOST}/x/_abcdefgh/_xyzabcde/",
        "@acme/widgets",
    ]


def test_native_pip_respects_existing_index_and_injects_temp_netrc(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    monkeypatch.setenv(
        "PIP_INDEX_URL",
        f"https://pypi.{STAGING_DOWNLOAD_HOST}/x/_abcdefgh/_xyzabcde/simple/",
    )
    calls: list[dict[str, Any]] = []
    netrc_texts: list[str] = []

    def hook(_cmd: list[str], env: dict[str, str]) -> None:
        netrc_texts.append(Path(env["NETRC"]).read_text(encoding="utf-8"))

    _capture_run(monkeypatch, calls, hook)

    result = runner.invoke(app, ["pip", "install", "demo"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == ["/bin/pip", "install", "demo"]
    assert calls[0]["env"]["PIP_INDEX_URL"] == (
        f"https://pypi.{STAGING_DOWNLOAD_HOST}/x/_abcdefgh/_xyzabcde/simple/"
    )
    assert netrc_texts == [
        f"machine pypi.{STAGING_DOWNLOAD_HOST} login __token__ password secret-token\n"
    ]


def test_native_pip_respects_custom_remote_cache_and_uses_profile_token(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    index_url = (
        f"https://pypi.{STAGING_DOWNLOAD_HOST}/r/_custpid1/piwheels/simple/"
    )
    monkeypatch.setenv("PIP_INDEX_URL", index_url)
    calls: list[dict[str, Any]] = []
    netrc_texts: list[str] = []

    def hook(_cmd: list[str], env: dict[str, str]) -> None:
        netrc_texts.append(Path(env["NETRC"]).read_text(encoding="utf-8"))

    _capture_run(monkeypatch, calls, hook)

    result = runner.invoke(app, ["pip", "download", "--no-deps", "simple-range==0.0.3"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == [
        "/bin/pip",
        "download",
        "--no-deps",
        "simple-range==0.0.3",
    ]
    assert calls[0]["env"]["PIP_INDEX_URL"] == index_url
    assert netrc_texts == [
        f"machine pypi.{STAGING_DOWNLOAD_HOST} login __token__ password secret-token\n"
    ]


def test_native_pip_local_remote_cache_netrc_uses_hostname_without_port(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    monkeypatch.setenv(
        "PIP_INDEX_URL",
        "http://localhost:8788/native/pypi/r/_custpid1/piwheels/simple/",
    )
    calls: list[dict[str, Any]] = []
    netrc_texts: list[str] = []

    def hook(_cmd: list[str], env: dict[str, str]) -> None:
        netrc_texts.append(Path(env["NETRC"]).read_text(encoding="utf-8"))

    _capture_run(monkeypatch, calls, hook)

    result = runner.invoke(app, ["pip", "download", "--no-deps", "simple-range==0.0.3"])

    assert result.exit_code == 0
    assert netrc_texts == ["machine localhost login __token__ password secret-token\n"]


def test_native_pip_isolate_overrides_index_without_writing_credentials(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    calls: list[dict[str, Any]] = []
    netrc_texts: list[str] = []

    def hook(_cmd: list[str], env: dict[str, str]) -> None:
        netrc_texts.append(Path(env["NETRC"]).read_text(encoding="utf-8"))

    _capture_run(monkeypatch, calls, hook)

    result = runner.invoke(
        app,
        [
            "pip",
            "--rvs-repo",
            "repo-pypi",
            "--rvs-native-config",
            "isolate",
            "install",
            "demo",
        ],
    )

    assert result.exit_code == 0
    assert calls[0]["cmd"] == [
        "/bin/pip",
        "install",
        "--index-url",
        f"https://pypi.{STAGING_DOWNLOAD_HOST}/x/_abcdefgh/_xyzabcde/simple/",
        "demo",
    ]
    assert calls[0]["env"]["PIP_CONFIG_FILE"] == os.devnull
    assert netrc_texts == [
        f"machine pypi.{STAGING_DOWNLOAD_HOST} login __token__ password secret-token\n"
    ]


def test_native_pip_preserves_multi_part_pip_command_prefix(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    monkeypatch.setattr(native_runner.tools, "pip_cmd", lambda: ["/bin/python", "-m", "pip"])
    calls: list[dict[str, Any]] = []
    _capture_run(monkeypatch, calls)

    result = runner.invoke(app, ["pip", "--rvs-repo", "repo-pypi", "install", "demo"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == [
        "/bin/python",
        "-m",
        "pip",
        "install",
        "--index-url",
        f"https://pypi.{STAGING_DOWNLOAD_HOST}/x/_abcdefgh/_xyzabcde/simple/",
        "demo",
    ]


def test_native_uv_repo_override_sets_index_publish_env_and_netrc(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    calls: list[dict[str, Any]] = []
    _capture_run(monkeypatch, calls)

    result = runner.invoke(app, ["uv", "--rvs-repo", "repo-pypi", "sync", "--locked"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == ["/bin/uv", "sync", "--locked"]
    assert calls[0]["env"]["UV_DEFAULT_INDEX"] == (
        f"https://pypi.{STAGING_DOWNLOAD_HOST}/x/_abcdefgh/_xyzabcde/simple/"
    )
    assert calls[0]["env"]["UV_PUBLISH_URL"] == (
        f"https://pypi.{STAGING_UPLOAD_HOST}/x/_abcdefgh/_xyzabcde/"
    )
    assert calls[0]["env"]["UV_PUBLISH_USERNAME"] == "__token__"
    assert calls[0]["env"]["UV_PUBLISH_PASSWORD"] == "secret-token"
    assert "NETRC" in calls[0]["env"]


def test_native_twine_repo_override_sets_ephemeral_upload_credentials(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    calls: list[dict[str, Any]] = []
    _capture_run(monkeypatch, calls)

    result = runner.invoke(app, ["twine", "--rvs-repo", "repo-pypi", "upload", "dist/demo.whl"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == ["/bin/twine", "upload", "dist/demo.whl"]
    assert calls[0]["env"]["TWINE_REPOSITORY_URL"] == (
        f"https://pypi.{STAGING_UPLOAD_HOST}/x/_abcdefgh/_xyzabcde/"
    )
    assert calls[0]["env"]["TWINE_USERNAME"] == "__token__"
    assert calls[0]["env"]["TWINE_PASSWORD"] == "secret-token"


def test_native_maven_repo_override_generates_temp_settings(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    calls: list[dict[str, Any]] = []
    settings_texts: list[str] = []

    def hook(cmd: list[str], _env: dict[str, str]) -> None:
        settings_path = Path(cmd[cmd.index("--settings") + 1])
        settings_texts.append(settings_path.read_text(encoding="utf-8"))

    _capture_run(monkeypatch, calls, hook)

    result = runner.invoke(app, ["mvn", "--rvs-repo", "repo-maven", "deploy"])

    assert result.exit_code == 0
    assert calls[0]["cmd"][0:2] == ["/bin/mvn", "--settings"]
    assert calls[0]["cmd"][-1] == (
        f"-DaltDeploymentRepository=rvs-private::default::https://maven.{STAGING_UPLOAD_HOST}/x/_abcdefgh/_xyzabcde/"
    )
    assert "<id>rvs-private</id>" in settings_texts[0]
    assert "<username>__token__</username>" in settings_texts[0]
    assert "<password>secret-token</password>" in settings_texts[0]
