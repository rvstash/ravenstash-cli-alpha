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
STAGING_API_URL = "https://control.example.test"
PYPI_READ_URL = "https://python-read.example.test"
PYPI_PUSH_URL = "https://python-write.example.test"
PYPI_CACHE_URL = "https://python-cache.example.test"
NPM_READ_URL = "https://javascript-read.example.test"
NPM_PUSH_URL = "https://javascript-write.example.test"
NPM_CACHE_URL = "https://javascript-cache.example.test"
MAVEN_READ_URL = "https://java-read.example.test"
MAVEN_PUSH_URL = "https://java-write.example.test"
MAVEN_CACHE_URL = "https://java-cache.example.test"
PYPI_READ_HOST = "python-read.example.test"
PYPI_CACHE_HOST = "python-cache.example.test"
NPM_READ_HOST = "javascript-read.example.test"
NPM_PUSH_HOST = "javascript-write.example.test"


def _native_endpoints() -> cfg_mod.NativeRegistryEndpoints:
    return cfg_mod.NativeRegistryEndpoints(
        pypi=cfg_mod.PackageRegistryEndpoints(PYPI_READ_URL, PYPI_PUSH_URL, PYPI_CACHE_URL),
        npm=cfg_mod.PackageRegistryEndpoints(NPM_READ_URL, NPM_PUSH_URL, NPM_CACHE_URL),
        maven=cfg_mod.PackageRegistryEndpoints(MAVEN_READ_URL, MAVEN_PUSH_URL, MAVEN_CACHE_URL),
        oci_registry_base_url="https://images.example.test",
    )


class _Completed:
    returncode = 0


class _JsonResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def json(self) -> Any:
        return self.payload


class _FakeDevApi:
    def get(self, path: str, params=None) -> _JsonResponse:
        if path == "/v0/customers":
            return _JsonResponse(
                [
                    {
                        "customer_id": "cus_staging",
                        "customer_unique_ref": "_custpid1",
                    }
                ]
            )
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
                    "workspace_unique_ref": "w_abcdefgh",
                    "workspace_name": "staging",
                    "repository_unique_ref": "r_xyzabcde",
                },
            }
        )

    def post(self, path: str, json: dict[str, Any] | None = None) -> _JsonResponse:
        if path == "/v0/remote-package-credentials":
            assert json is not None
            assert json["customer_id"] == "cus_staging"
            assert json["registry_kind"] == "pypi"
            assert json["route_kind"] in {"remote_custom", "remote_official"}
            return _JsonResponse({"access_token": "remote-secret-token"})
        assert path == "/v0/package-credentials"
        assert json is not None
        assert json["operations"] in (["download"], ["upload"], ["download", "upload"])
        return _JsonResponse(
            {
                "access_token": "secret-token",
                "native_path": "/staging/repo",
                "workspace_name": "staging",
                "repository_name": "repo",
            }
        )


def _isolate_config(monkeypatch: Any, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvs"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text(
        f"""
default_profile = "staging"

[profiles.staging]
api_url = "{STAGING_API_URL}"
customer_id = "cus_staging"
customer_unique_id = "custpid1"

[profiles.staging.native_registries.pypi]
read_base_url = "{PYPI_READ_URL}"
push_base_url = "{PYPI_PUSH_URL}"
cache_base_url = "{PYPI_CACHE_URL}"

[profiles.staging.native_registries.npm]
read_base_url = "{NPM_READ_URL}"
push_base_url = "{NPM_PUSH_URL}"
cache_base_url = "{NPM_CACHE_URL}"

[profiles.staging.native_registries.maven]
read_base_url = "{MAVEN_READ_URL}"
push_base_url = "{MAVEN_PUSH_URL}"
cache_base_url = "{MAVEN_CACHE_URL}"

[profiles.staging.native_registries.oci]
registry_base_url = "https://images.example.test"

[profiles.staging.registries.pypi]
default_repo = "w_abcdefgh/r_xyzabcde"

[profiles.staging.registries.npm]
default_repo = "w_abcdefgh/r_xyzabcde"

[profiles.staging.registries.maven]
default_repo = "w_abcdefgh/r_xyzabcde"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(cfg_mod, "PROFILE_ENV_FILE", config_dir / "profiles.env")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RVS_TOKEN", "raw-control-token")
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
        assert "RVS_TOKEN" not in env
        if hook:
            hook(cmd, env)
        calls.append({"cmd": cmd, "env": env.copy()})
        return _Completed()

    monkeypatch.setattr(native_runner.subprocess, "run", fake_run)


def test_native_commands_request_only_the_operations_they_need() -> None:
    assert native_runner._operations_for("pip", ["install", "demo"]) == ("download",)
    assert native_runner._operations_for("uv", ["publish", "dist/demo.whl"]) == ("upload",)
    assert native_runner._operations_for("twine", ["upload", "dist/*"]) == ("upload",)
    assert native_runner._operations_for("npm", ["ci"]) == ("download",)
    assert native_runner._operations_for("npm", ["publish"]) == ("upload",)
    assert native_runner._operations_for("npm", ["unpublish", "demo@1.0.0"]) == (
        "download",
        "upload",
    )
    assert native_runner._operations_for("npm", ["deprecate", "demo@1", "old"]) == (
        "download",
        "upload",
    )
    assert native_runner._operations_for("npm", ["dist-tag", "add", "demo@1", "next"]) == (
        "download",
        "upload",
    )
    assert native_runner._operations_for("npm", ["dist-tag", "ls", "demo"]) == (
        "download",
    )
    assert native_runner._operations_for("mvn", ["test"]) == ("download",)
    assert native_runner._operations_for("mvn", ["deploy"]) == ("download", "upload")
    assert native_runner._operations_for(
        "mvn",
        ["org.apache.maven.plugins:maven-deploy-plugin:3.1.3:deploy-file"],
    ) == ("download", "upload")


def test_ravenstash_url_kind_accepts_public_hosts_and_local_normalized_routes() -> None:
    def url_kind(url: str, *, endpoints=None) -> str | None:
        return native_runner._ravenstash_url_kind(
            url,
            native_registries=endpoints or _native_endpoints(),
        )

    assert url_kind(f"{NPM_READ_URL}/w_abcdefgh/r_xyzabcde/") == "npm"
    assert url_kind(f"{PYPI_READ_URL}/w_abcdefgh/r_xyzabcde/simple/") == "pypi"
    assert (
        url_kind(
            "http://localhost:43101/registry/maven/w_abcdefgh/r_xyzabcde/com/example/demo/",
            endpoints=cfg_mod.NativeRegistryEndpoints(
                pypi=cfg_mod.PackageRegistryEndpoints(
                    "http://localhost:43101/registry/pypi",
                    "http://localhost:43102/registry/pypi",
                    "http://localhost:43101/registry/pypi",
                ),
                npm=cfg_mod.PackageRegistryEndpoints(
                    "http://localhost:43101/registry/npm",
                    "http://localhost:43102/registry/npm",
                    "http://localhost:43101/registry/npm",
                ),
                maven=cfg_mod.PackageRegistryEndpoints(
                    "http://localhost:43101/registry/maven",
                    "http://localhost:43102/registry/maven",
                    "http://localhost:43101/registry/maven",
                ),
                oci_registry_base_url="http://localhost:43101",
            ),
        )
        == "maven"
    )
    assert (
        url_kind(
            f"{PYPI_CACHE_URL}/c/piwheels/simple/",
        )
        == "pypi"
    )
    assert url_kind(f"{PYPI_CACHE_URL}/o/pypiorg/simple/") == "pypi"
    assert url_kind(f"{NPM_CACHE_URL}/c/_xyzabcde/") == "npm"
    assert url_kind("https://npm.example.test/w_abcdefgh/r_xyzabcde/") is None
    assert url_kind("https://pkg-staging.example.test/w_abcdefgh/r_xyzabcde/") is None
    assert url_kind(f"{NPM_READ_URL}/o/npmjs/") is None
    assert url_kind(f"{NPM_READ_URL}/c/private-upstream/") is None
    assert url_kind(f"{NPM_CACHE_URL}/w_abcdefgh/r_xyzabcde/") is None
    assert url_kind(f"{NPM_READ_URL}/w_abcdefgh/") is None


def test_ravenstash_url_kind_rejects_attacker_lookalike_origins() -> None:
    def url_kind(url: str) -> str | None:
        return native_runner._ravenstash_url_kind(
            url,
            native_registries=_native_endpoints(),
        )

    assert url_kind("https://npm.pkg.attacker.example/w_abcdefgh/r_xyzabcde/") is None
    assert url_kind("https://attacker.example/native/pypi/other/customer/simple/") is None
    assert (
        url_kind("https://npm.pkg-staging.example.test.attacker.example/w_abcdefgh/r_xyzabcde/")
        is None
    )
    assert (
        url_kind("https://npm.pkg-staging.example.test@attacker.example/w_abcdefgh/r_xyzabcde/")
        is None
    )
    assert url_kind("http://npm.pkg-staging.example.test/w_abcdefgh/r_xyzabcde/") is None
    assert url_kind("https://npm.pkg-staging.example.test:444/w_abcdefgh/r_xyzabcde/") is None
    assert url_kind("https://npm.pkg-staging.example.test:bad/w_abcdefgh/r_xyzabcde/") is None


def test_native_npm_respects_project_npmrc_and_injects_path_scoped_auth(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    (tmp_path / ".npmrc").write_text(
        f"@acme:registry={NPM_READ_URL}/w_abcdefgh/r_xyzabcde/\n",
        encoding="utf-8",
    )
    calls: list[dict[str, Any]] = []
    _capture_run(monkeypatch, calls)

    result = runner.invoke(app, ["npm", "install", "@acme/widgets"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == ["/bin/npm", "install", "@acme/widgets"]
    assert "NPM_CONFIG_REGISTRY" not in calls[0]["env"]
    assert (
        calls[0]["env"][f"NPM_CONFIG_//{NPM_READ_HOST}/w_abcdefgh/r_xyzabcde/:_authToken"]
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

    result = runner.invoke(app, ["npm", "--rvs-target", "staging/repo-npm", "publish"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == [
        "/bin/npm",
        "publish",
        "--registry",
        f"{NPM_PUSH_URL}/staging/repo/",
    ]
    assert calls[0]["env"]["NPM_CONFIG_REGISTRY"] == (f"{NPM_PUSH_URL}/staging/repo/")
    assert (
        calls[0]["env"][f"NPM_CONFIG_//{NPM_PUSH_HOST}/staging/repo/:_authToken"] == "secret-token"
    )


def test_native_npm_repo_override_uses_upload_registry_for_unpublish(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    calls: list[dict[str, Any]] = []
    _capture_run(monkeypatch, calls)

    result = runner.invoke(
        app,
        ["npm", "--rvs-target", "staging/repo-npm", "unpublish", "demo@1.0.0"],
    )

    assert result.exit_code == 0
    assert calls[0]["cmd"] == [
        "/bin/npm",
        "unpublish",
        "--registry",
        f"{NPM_PUSH_URL}/staging/repo/",
        "demo@1.0.0",
    ]
    assert calls[0]["env"]["NPM_CONFIG_REGISTRY"] == f"{NPM_PUSH_URL}/staging/repo/"
    assert (
        calls[0]["env"][f"NPM_CONFIG_//{NPM_PUSH_HOST}/staging/repo/:_authToken"] == "secret-token"
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
            "--rvs-target",
            "staging/repo-npm",
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
        f"{NPM_READ_URL}/staging/repo/",
        "@acme/widgets",
    ]


def test_native_npm_isolate_uses_distinct_empty_config_files(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    calls: list[dict[str, Any]] = []
    config_snapshots: list[tuple[Path, Path, str, str]] = []

    def hook(_cmd: list[str], env: dict[str, str]) -> None:
        user_config = Path(env["NPM_CONFIG_USERCONFIG"])
        global_config = Path(env["NPM_CONFIG_GLOBALCONFIG"])
        config_snapshots.append(
            (
                user_config,
                global_config,
                user_config.read_text(encoding="utf-8"),
                global_config.read_text(encoding="utf-8"),
            )
        )

    _capture_run(monkeypatch, calls, hook)

    result = runner.invoke(
        app,
        [
            "npm",
            "--rvs-target",
            "staging/repo-npm",
            "--rvs-native-config",
            "isolate",
            "install",
            "@acme/widgets",
        ],
    )

    assert result.exit_code == 0
    user_config, global_config, user_text, global_text = config_snapshots[0]
    assert user_config != global_config
    assert user_text == global_text == ""
    assert not user_config.exists()
    assert not global_config.exists()


def test_native_pip_respects_existing_index_and_injects_temp_netrc(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    monkeypatch.delenv("PIP_KEYRING_PROVIDER", raising=False)
    monkeypatch.setenv(
        "PIP_INDEX_URL",
        f"{PYPI_READ_URL}/w_abcdefgh/r_xyzabcde/simple/",
    )
    calls: list[dict[str, Any]] = []
    netrc_texts: list[str] = []

    def hook(_cmd: list[str], env: dict[str, str]) -> None:
        netrc_texts.append(Path(env["NETRC"]).read_text(encoding="utf-8"))

    _capture_run(monkeypatch, calls, hook)

    result = runner.invoke(app, ["pip", "install", "demo"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == ["/bin/pip", "install", "demo"]
    assert calls[0]["env"]["PIP_INDEX_URL"] == (f"{PYPI_READ_URL}/w_abcdefgh/r_xyzabcde/simple/")
    assert "PIP_KEYRING_PROVIDER" not in calls[0]["env"]
    assert netrc_texts == [f"machine {PYPI_READ_HOST} login __token__ password secret-token\n"]
    assert not Path(calls[0]["env"]["NETRC"]).exists()


def test_native_pip_exchanges_profile_token_for_scoped_remote_credential(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    index_url = f"{PYPI_CACHE_URL}/c/piwheels/simple/"
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
        f"machine {PYPI_CACHE_HOST} login __token__ password remote-secret-token\n"
    ]


def test_native_pip_local_remote_cache_netrc_uses_hostname_without_port(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    config_path = cfg_mod.CONFIG_FILE
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            PYPI_CACHE_URL,
            "http://localhost:43101/registry/pypi",
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "PIP_INDEX_URL",
        "http://localhost:43101/registry/pypi/c/piwheels/simple/",
    )
    calls: list[dict[str, Any]] = []
    netrc_texts: list[str] = []

    def hook(_cmd: list[str], env: dict[str, str]) -> None:
        netrc_texts.append(Path(env["NETRC"]).read_text(encoding="utf-8"))

    _capture_run(monkeypatch, calls, hook)

    result = runner.invoke(app, ["pip", "download", "--no-deps", "simple-range==0.0.3"])

    assert result.exit_code == 0
    assert netrc_texts == ["machine localhost login __token__ password remote-secret-token\n"]


def test_native_pip_exchanges_official_remote_credential(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    monkeypatch.setenv(
        "PIP_INDEX_URL",
        f"{PYPI_CACHE_URL}/o/pypiorg/simple/",
    )
    captured: list[str] = []

    def hook(_cmd: list[str], env: dict[str, str]) -> None:
        captured.append(Path(env["NETRC"]).read_text(encoding="utf-8"))

    _capture_run(monkeypatch, [], hook)

    result = runner.invoke(app, ["pip", "download", "demo"])

    assert result.exit_code == 0
    assert captured == [f"machine {PYPI_CACHE_HOST} login __token__ password remote-secret-token\n"]


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
            "--rvs-target",
            "staging/repo-pypi",
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
        f"{PYPI_READ_URL}/staging/repo/simple/",
        "demo",
    ]
    assert calls[0]["env"]["PIP_CONFIG_FILE"] == os.devnull
    assert netrc_texts == [f"machine {PYPI_READ_HOST} login __token__ password secret-token\n"]


def test_native_pip_preserves_multi_part_pip_command_prefix(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    monkeypatch.setattr(native_runner.tools, "pip_cmd", lambda: ["/bin/python", "-m", "pip"])
    calls: list[dict[str, Any]] = []
    _capture_run(monkeypatch, calls)

    result = runner.invoke(app, ["pip", "--rvs-target", "staging/repo-pypi", "install", "demo"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == [
        "/bin/python",
        "-m",
        "pip",
        "install",
        "--index-url",
        f"{PYPI_READ_URL}/staging/repo/simple/",
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

    result = runner.invoke(app, ["uv", "--rvs-target", "staging/repo-pypi", "sync", "--locked"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == ["/bin/uv", "sync", "--locked"]
    assert calls[0]["env"]["UV_DEFAULT_INDEX"] == (f"{PYPI_READ_URL}/staging/repo/simple/")
    assert calls[0]["env"]["UV_PUBLISH_URL"] == (f"{PYPI_PUSH_URL}/staging/repo/")
    assert calls[0]["env"]["UV_PUBLISH_USERNAME"] == "__token__"
    assert calls[0]["env"]["UV_PUBLISH_PASSWORD"] == "secret-token"
    assert "NETRC" in calls[0]["env"]
    assert not Path(calls[0]["env"]["NETRC"]).exists()


def test_native_twine_repo_override_sets_ephemeral_upload_credentials(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    calls: list[dict[str, Any]] = []
    _capture_run(monkeypatch, calls)

    result = runner.invoke(
        app,
        ["twine", "--rvs-target", "staging/repo-pypi", "upload", "dist/demo.whl"],
    )

    assert result.exit_code == 0
    assert calls[0]["cmd"] == ["/bin/twine", "upload", "dist/demo.whl"]
    assert calls[0]["env"]["TWINE_REPOSITORY_URL"] == (f"{PYPI_PUSH_URL}/staging/repo/")
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

    result = runner.invoke(app, ["mvn", "--rvs-target", "staging/repo-maven", "deploy"])

    assert result.exit_code == 0
    assert calls[0]["cmd"][0:2] == ["/bin/mvn", "--settings"]
    assert calls[0]["cmd"][-1] == (
        f"-DaltDeploymentRepository=rvs-private::default::{MAVEN_PUSH_URL}/staging/repo/"
    )
    assert "<id>rvs-private</id>" in settings_texts[0]
    assert "<username>__token__</username>" in settings_texts[0]
    assert "<password>secret-token</password>" in settings_texts[0]
    assert not Path(calls[0]["cmd"][calls[0]["cmd"].index("--settings") + 1]).exists()


def test_native_maven_deploy_file_injects_upload_destination(
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
            "mvn",
            "--rvs-target",
            "staging/repo-maven",
            "org.apache.maven.plugins:maven-deploy-plugin:3.1.3:deploy-file",
            "-Dfile=demo.jar",
            "-DpomFile=demo.pom",
        ],
    )

    assert result.exit_code == 0
    assert calls[0]["cmd"][-2:] == [
        "-DrepositoryId=rvs-private",
        f"-Durl={MAVEN_PUSH_URL}/staging/repo/",
    ]
