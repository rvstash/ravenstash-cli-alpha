from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from rvs import config as cfg_mod
from rvs.cli import app
from rvs.client import ApiClient
from rvs.native import runner as native_runner
from typer.testing import CliRunner


if TYPE_CHECKING:
    from collections.abc import Callable


runner = CliRunner()
STAGING_API_URL = "https://control.example.test"
PYPI_READ_URL = "https://python-read.example.test"
PYPI_PUSH_URL = "https://python-write.example.test"
PYPI_MIRROR_URL = "https://python-mirror.example.test"
NPM_READ_URL = "https://javascript-read.example.test"
NPM_PUSH_URL = "https://javascript-write.example.test"
NPM_MIRROR_URL = "https://javascript-mirror.example.test"
MAVEN_READ_URL = "https://java-read.example.test"
MAVEN_PUSH_URL = "https://java-write.example.test"
MAVEN_MIRROR_URL = "https://java-mirror.example.test"
PYPI_READ_HOST = "python-read.example.test"
PYPI_MIRROR_HOST = "python-mirror.example.test"
NPM_READ_HOST = "javascript-read.example.test"
NPM_PUSH_HOST = "javascript-write.example.test"


def _native_endpoints() -> cfg_mod.NativeRegistryEndpoints:
    return cfg_mod.NativeRegistryEndpoints(
        pypi=cfg_mod.PackageRegistryEndpoints(PYPI_READ_URL, PYPI_PUSH_URL, PYPI_MIRROR_URL),
        npm=cfg_mod.PackageRegistryEndpoints(NPM_READ_URL, NPM_PUSH_URL, NPM_MIRROR_URL),
        maven=cfg_mod.PackageRegistryEndpoints(MAVEN_READ_URL, MAVEN_PUSH_URL, MAVEN_MIRROR_URL),
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
        if path == "/customers":
            return _JsonResponse(
                [
                    {
                        "customer_id": "cus_staging",
                        "customer_unique_ref": "_custpid1",
                    }
                ]
            )
        assert path == "/repositories/resolve"
        return _JsonResponse(
            {
                "customer": {
                    "customer_id": "cus_staging",
                    "customer_unique_ref": "_custpid1",
                },
                "repository": {
                    "repository_name": "repo",
                    "namespace_unique_ref": "in_abcdefgh",
                    "namespace_name": "staging",
                    "namespace_realm": "internal",
                    "repository_unique_ref": "r_xyzabcde",
                },
            }
        )

    def issue_native(self, path: str, payload: dict):
        assert payload["duration_seconds"] == 14400
        return self.post(path, json=payload)

    def post(self, path: str, json: dict[str, Any] | None = None) -> _JsonResponse:
        if path == "/remote-package-credentials":
            assert json is not None
            assert json["customer_id"] == "cus_staging"
            assert json["registry_kind"] == "pypi"
            assert json["remote_cache_ref"]
            namespace = "o" if json["remote_cache_ref"] == "pypiorg" else "c"
            return _JsonResponse(
                {
                    "access_token": "rvs_sltBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBA",
                    "native_path": f"/{namespace}/{json['remote_cache_ref']}",
                }
            )
        assert path == "/package-credentials"
        assert json is not None
        assert json["operations"] in (["download"], ["upload"], ["download", "upload"])
        return _JsonResponse(
            {
                "access_token": "rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                "native_path": "/staging/repo",
                "namespace_name": "staging",
                "namespace_realm": "internal",
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
mirror_base_url = "{PYPI_MIRROR_URL}"

[profiles.staging.native_registries.npm]
read_base_url = "{NPM_READ_URL}"
push_base_url = "{NPM_PUSH_URL}"
mirror_base_url = "{NPM_MIRROR_URL}"

[profiles.staging.native_registries.maven]
read_base_url = "{MAVEN_READ_URL}"
push_base_url = "{MAVEN_PUSH_URL}"
mirror_base_url = "{MAVEN_MIRROR_URL}"

[profiles.staging.native_registries.oci]
registry_base_url = "https://images.example.test"

[profiles.staging.registries.pypi]
default_repo = "in_abcdefgh/r_xyzabcde"

[profiles.staging.registries.npm]
default_repo = "in_abcdefgh/r_xyzabcde"

[profiles.staging.registries.maven]
default_repo = "in_abcdefgh/r_xyzabcde"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(cfg_mod, "PROFILE_ENV_FILE", config_dir / "profiles.env")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RVS_TOKEN", "raw-control-token")
    monkeypatch.setattr(
        ApiClient,
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


@pytest.mark.parametrize(
    "wrong_token", ["rvs_ust" + "A" * 43, "rvs_art_v1_retired", "rvs_slt" + "B" * 43]
)
def test_native_wrapper_rejects_wrong_type_before_starting_child(
    monkeypatch, tmp_path, wrong_token
):
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    original_post = _FakeDevApi.post

    def wrong_credential(self, path, json=None):
        response = original_post(self, path, json)
        payload = response.json()
        payload["access_token"] = wrong_token
        return _JsonResponse(payload)

    monkeypatch.setattr(_FakeDevApi, "post", wrong_credential)
    calls = []
    _capture_run(monkeypatch, calls)
    result = runner.invoke(app, ["pip", "install", "demo"])
    assert result.exit_code != 0
    assert "Invalid public credential" in result.output
    assert wrong_token not in result.output
    assert calls == []


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
        "upload",
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

    assert url_kind(f"{NPM_READ_URL}/in_abcdefgh/r_xyzabcde/") == "npm"
    assert url_kind(f"{PYPI_READ_URL}/in_abcdefgh/r_xyzabcde/simple/") == "pypi"
    assert (
        url_kind(
            "http://localhost:43101/registry/maven/in_abcdefgh/r_xyzabcde/com/example/demo/",
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
            f"{PYPI_MIRROR_URL}/c/piwheels/simple/",
        )
        == "pypi"
    )
    assert url_kind(f"{PYPI_MIRROR_URL}/o/pypiorg/simple/") == "pypi"
    assert url_kind(f"{NPM_MIRROR_URL}/c/_xyzabcde/") == "npm"
    assert url_kind("https://npm.example.test/in_abcdefgh/r_xyzabcde/") is None
    assert url_kind("https://pkg-staging.example.test/in_abcdefgh/r_xyzabcde/") is None
    assert url_kind(f"{NPM_READ_URL}/o/npmjs/") is None
    assert url_kind(f"{NPM_READ_URL}/c/private-upstream/") is None
    assert url_kind(f"{NPM_MIRROR_URL}/in_abcdefgh/r_xyzabcde/") is None
    assert url_kind(f"{NPM_READ_URL}/in_abcdefgh/") is None


def test_ravenstash_url_kind_rejects_attacker_lookalike_origins() -> None:
    def url_kind(url: str) -> str | None:
        return native_runner._ravenstash_url_kind(
            url,
            native_registries=_native_endpoints(),
        )

    assert url_kind("https://npm.pkg.attacker.example/in_abcdefgh/r_xyzabcde/") is None
    assert url_kind("https://attacker.example/native/pypi/other/customer/simple/") is None
    assert (
        url_kind("https://npm.pkg-staging.example.test.attacker.example/in_abcdefgh/r_xyzabcde/")
        is None
    )
    assert (
        url_kind("https://npm.pkg-staging.example.test@attacker.example/in_abcdefgh/r_xyzabcde/")
        is None
    )
    assert url_kind("http://npm.pkg-staging.example.test/in_abcdefgh/r_xyzabcde/") is None
    assert url_kind("https://npm.pkg-staging.example.test:444/in_abcdefgh/r_xyzabcde/") is None
    assert url_kind("https://npm.pkg-staging.example.test:bad/in_abcdefgh/r_xyzabcde/") is None


def test_native_npm_respects_project_npmrc_and_injects_path_scoped_auth(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    (tmp_path / ".npmrc").write_text(
        f"@acme:registry={NPM_READ_URL}/in_abcdefgh/r_xyzabcde/\n",
        encoding="utf-8",
    )
    calls: list[dict[str, Any]] = []
    _capture_run(monkeypatch, calls)

    result = runner.invoke(app, ["npm", "install", "@acme/widgets"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == [
        "/bin/npm",
        "install",
        "--registry",
        f"{NPM_READ_URL}/staging/repo/",
        "@acme/widgets",
    ]
    assert calls[0]["env"]["NPM_CONFIG_REGISTRY"] == f"{NPM_READ_URL}/staging/repo/"
    assert (
        calls[0]["env"][f"NPM_CONFIG_//{NPM_READ_HOST}/staging/repo/:_authToken"]
        == "rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    )


@pytest.mark.parametrize(
    "tool,args",
    [
        ("npm", ["publish"]),
        ("uv", ["publish", "dist/demo.whl"]),
        ("twine", ["upload", "dist/demo.whl"]),
        ("mvn", ["deploy"]),
    ],
)
def test_native_publish_decline_does_not_launch(monkeypatch, tmp_path: Path, tool, args) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    calls = []
    _capture_run(monkeypatch, calls)
    result = runner.invoke(app, [tool, "--rvs-target", "staging/repo", *args], input="\n")
    assert result.exit_code != 0
    assert "Publish to staging/repo (personal)" in result.output
    assert not calls


@pytest.mark.parametrize(
    "flags,answer,published", [([], "n\n", False), ([], "y\n", True), (["--rvs-yes"], "", True)]
)
def test_native_detected_registry_confirms_resolved_account(
    monkeypatch, tmp_path: Path, flags, answer, published
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    monkeypatch.setenv("NPM_CONFIG_REGISTRY", f"{NPM_PUSH_URL}/staging/repo/")

    class OrgApi(_FakeDevApi):
        def get(self, path, params=None):
            payload = super().get(path, params).json()
            payload["customer"].update(account_type="organization", account_label="YYYY")
            return _JsonResponse(payload)

    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: OrgApi()))
    calls = []
    _capture_run(monkeypatch, calls)
    result = runner.invoke(app, ["npm", *flags, "publish"], input=answer)
    assert (result.exit_code == 0) == published, result.output
    assert bool(calls) == published
    if not flags:
        assert "Publish to staging/repo (org:YYYY)" in result.output
    if calls:
        assert "--rvs-yes" not in calls[0]["cmd"]


def test_native_npm_repo_override_uses_upload_registry_for_publish(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    calls: list[dict[str, Any]] = []
    _capture_run(monkeypatch, calls)

    result = runner.invoke(app, ["npm", "--rvs-target", "staging/repo-npm", "publish"], input="y\n")

    assert result.exit_code == 0
    assert calls[0]["cmd"] == [
        "/bin/npm",
        "publish",
        "--registry",
        f"{NPM_PUSH_URL}/staging/repo/",
    ]
    assert calls[0]["env"]["NPM_CONFIG_REGISTRY"] == (f"{NPM_PUSH_URL}/staging/repo/")
    assert (
        calls[0]["env"][f"NPM_CONFIG_//{NPM_PUSH_HOST}/staging/repo/:_authToken"]
        == "rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
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
        calls[0]["env"][f"NPM_CONFIG_//{NPM_PUSH_HOST}/staging/repo/:_authToken"]
        == "rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    )


def test_native_npm_repo_override_uses_upload_registry_for_dist_tag_list(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    calls: list[dict[str, Any]] = []
    _capture_run(monkeypatch, calls)

    result = runner.invoke(
        app,
        ["npm", "--rvs-target", "staging/repo-npm", "dist-tag", "ls", "demo"],
    )

    assert result.exit_code == 0
    assert calls[0]["cmd"] == [
        "/bin/npm",
        "dist-tag",
        "--registry",
        f"{NPM_PUSH_URL}/staging/repo/",
        "ls",
        "demo",
    ]
    assert calls[0]["env"]["NPM_CONFIG_REGISTRY"] == f"{NPM_PUSH_URL}/staging/repo/"
    assert (
        calls[0]["env"][f"NPM_CONFIG_//{NPM_PUSH_HOST}/staging/repo/:_authToken"]
        == "rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
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
        f"{PYPI_READ_URL}/in_abcdefgh/r_xyzabcde/simple/",
    )
    calls: list[dict[str, Any]] = []
    netrc_texts: list[str] = []

    def hook(_cmd: list[str], env: dict[str, str]) -> None:
        netrc_texts.append(Path(env["NETRC"]).read_text(encoding="utf-8"))

    _capture_run(monkeypatch, calls, hook)

    result = runner.invoke(app, ["pip", "install", "demo"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == [
        "/bin/pip",
        "install",
        "--index-url",
        f"{PYPI_READ_URL}/staging/repo/simple/",
        "demo",
    ]
    assert calls[0]["env"]["PIP_INDEX_URL"] == (f"{PYPI_READ_URL}/staging/repo/simple/")
    assert "PIP_KEYRING_PROVIDER" not in calls[0]["env"]
    assert netrc_texts == [
        f"machine {PYPI_READ_HOST} login __token__ password rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n"
    ]
    assert not Path(calls[0]["env"]["NETRC"]).exists()


def test_native_pip_exchanges_profile_token_for_scoped_remote_credential(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    index_url = f"{PYPI_MIRROR_URL}/c/piwheels/simple/"
    monkeypatch.setenv("PIP_INDEX_URL", index_url)
    monkeypatch.setattr(
        native_runner,
        "_resolve_route",
        lambda *a, **kw: native_runner.RegistryRoute(
            "pypi",
            PYPI_MIRROR_URL,
            None,
            "c",
            "piwheels",
            "rvs_sltBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBA",
        ),
    )
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
        "--index-url",
        index_url,
        "--no-deps",
        "simple-range==0.0.3",
    ]
    assert calls[0]["env"]["PIP_INDEX_URL"] == index_url
    assert netrc_texts == [
        f"machine {PYPI_MIRROR_HOST} login __token__ password rvs_sltBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBA\n"
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
            PYPI_MIRROR_URL,
            "http://localhost:43101/registry/pypi",
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "PIP_INDEX_URL",
        "http://localhost:43101/registry/pypi/c/piwheels/simple/",
    )
    monkeypatch.setattr(
        native_runner,
        "_resolve_route",
        lambda *a, **kw: native_runner.RegistryRoute(
            "pypi",
            "http://localhost:43101/registry/pypi",
            None,
            "c",
            "piwheels",
            "rvs_sltBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBA",
        ),
    )
    calls: list[dict[str, Any]] = []
    netrc_texts: list[str] = []

    def hook(_cmd: list[str], env: dict[str, str]) -> None:
        netrc_texts.append(Path(env["NETRC"]).read_text(encoding="utf-8"))

    _capture_run(monkeypatch, calls, hook)

    result = runner.invoke(app, ["pip", "download", "--no-deps", "simple-range==0.0.3"])

    assert result.exit_code == 0
    assert netrc_texts == [
        "machine localhost login __token__ password rvs_sltBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBA\n"
    ]


def test_native_pip_exchanges_official_remote_credential(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    monkeypatch.setenv(
        "PIP_INDEX_URL",
        f"{PYPI_MIRROR_URL}/o/pypiorg/simple/",
    )
    monkeypatch.setattr(
        native_runner,
        "_resolve_route",
        lambda *a, **kw: native_runner.RegistryRoute(
            "pypi",
            PYPI_MIRROR_URL,
            None,
            "o",
            "pypiorg",
            "rvs_sltBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBA",
        ),
    )
    captured: list[str] = []

    def hook(_cmd: list[str], env: dict[str, str]) -> None:
        captured.append(Path(env["NETRC"]).read_text(encoding="utf-8"))

    _capture_run(monkeypatch, [], hook)

    result = runner.invoke(app, ["pip", "download", "demo"])

    assert result.exit_code == 0
    assert captured == [
        f"machine {PYPI_MIRROR_HOST} login __token__ password rvs_sltBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBA\n"
    ]


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
    assert netrc_texts == [
        f"machine {PYPI_READ_HOST} login __token__ password rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n"
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
    assert "UV_PUBLISH_PASSWORD" not in calls[0]["env"]
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
        ["twine", "--rvs-yes", "--rvs-target", "staging/repo-pypi", "upload", "dist/demo.whl"],
    )

    assert result.exit_code == 0
    assert calls[0]["cmd"] == ["/bin/twine", "upload", "dist/demo.whl"]
    assert calls[0]["env"]["TWINE_REPOSITORY_URL"] == (f"{PYPI_PUSH_URL}/staging/repo/")
    assert calls[0]["env"]["TWINE_USERNAME"] == "__token__"
    assert calls[0]["env"]["TWINE_PASSWORD"] == "rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


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

    result = runner.invoke(
        app, ["mvn", "--rvs-yes", "--rvs-target", "staging/repo-maven", "deploy"]
    )

    assert result.exit_code == 0
    assert calls[0]["cmd"][0:2] == ["/bin/mvn", "--settings"]
    assert calls[0]["cmd"][-1] == (
        f"-DaltDeploymentRepository=rvs-private::default::{MAVEN_PUSH_URL}/staging/repo/"
    )
    assert "<id>rvs-private</id>" in settings_texts[0]
    assert "<mirrorOf>central</mirrorOf>" in settings_texts[0]
    assert "<username>__token__</username>" in settings_texts[0]
    assert (
        "<password>rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA</password>"
        in settings_texts[0]
    )
    assert not Path(calls[0]["cmd"][calls[0]["cmd"].index("--settings") + 1]).exists()


def test_native_maven_read_only_mirror_uses_only_download_route(tmp_path: Path) -> None:
    route = native_runner.RegistryRoute(
        kind="maven",
        read_base_url=MAVEN_MIRROR_URL,
        push_base_url=None,
        namespace_unique_ref="o",
        repository_unique_ref="maven-central",
        package_token="rvs_sltBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBA",
    )
    cmd = [
        "/bin/mvn",
        "org.apache.maven.plugins:maven-dependency-plugin:3.8.1:get",
        "-Dartifact=com.example:demo:1.0.0",
    ]

    native_runner._inject_override(
        "mvn",
        cmd,
        1,
        {},
        route,
        route.package_token,
        tmp_path,
        isolate=True,
    )

    settings_path = Path(cmd[cmd.index("--settings") + 1])
    settings_text = settings_path.read_text(encoding="utf-8")
    expected_url = f"{MAVEN_MIRROR_URL}/o/maven-central/"
    assert expected_url in settings_text
    assert "<mirrorOf>*</mirrorOf>" in settings_text
    assert MAVEN_PUSH_URL not in settings_text


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
            "--rvs-yes",
            "-Dfile=demo.jar",
            "-DpomFile=demo.pom",
        ],
    )

    assert result.exit_code == 0
    assert calls[0]["cmd"][-2:] == [
        "-DrepositoryId=rvs-private",
        f"-Durl={MAVEN_PUSH_URL}/staging/repo/",
    ]


@pytest.mark.parametrize(
    "tool,args",
    [
        ("pip", ["install", "demo"]),
        ("uv", ["lock"]),
        ("npm", ["ci"]),
        ("mvn", ["verify"]),
        ("twine", ["upload", "dist/demo.whl"]),
    ],
)
def test_missing_target_never_launches_or_infers_from_native_config(
    monkeypatch, tmp_path, tool, args
):
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    path = cfg_mod.CONFIG_FILE
    path.write_text(path.read_text().replace('default_repo = "in_abcdefgh/r_xyzabcde"', ""))
    monkeypatch.setenv("PIP_INDEX_URL", f"{PYPI_READ_URL}/staging/repo/simple/")
    calls = []
    _capture_run(monkeypatch, calls)
    result = runner.invoke(app, [tool, *args])
    assert result.exit_code != 0
    assert "No Ravenstash target is selected" in result.output
    assert not calls


@pytest.mark.parametrize(
    "tool,args,name,content",
    [
        (
            "uv",
            ["sync", "--locked"],
            "uv.lock",
            """version = 1
[[package]]
name = "demo"
version = "1.0"
source = { registry = "https://vendor.test/simple" }
wheels = [{url = "https://user:do-not-print@vendor.test/secret-path/demo.whl?token=secret-query"}]
""",
        ),
        (
            "npm",
            ["ci"],
            "package-lock.json",
            '{"packages":{"node_modules/demo":{"resolved":"https://vendor.test/demo.tgz","integrity":"unchanged"}}}',
        ),
        ("pip", ["install", "-r", "requirements.txt"], "requirements.txt", "-r nested.txt\n"),
    ],
)
def test_foreign_lock_sources_warn_without_changes(
    monkeypatch, tmp_path, tool, args, name, content
):
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    path = tmp_path / name
    path.write_text(content)
    (tmp_path / "nested.txt").write_text(
        "--extra-index-url https://vendor.test/simple\ndemo==1.0\n"
    )
    calls = []
    _capture_run(monkeypatch, calls)
    result = runner.invoke(app, [tool, "--rvs-target", "staging/repo", *args])
    assert result.exit_code == 0, result.output
    assert "Additional native sources" in result.output
    assert "do-not-print" not in result.output
    assert "secret-path" not in result.output
    assert "secret-query" not in result.output
    assert path.read_text() == content
    assert len(calls) == 1
    if tool == "uv":
        assert calls[0]["cmd"] == ["/bin/uv", "sync", "--locked"]


def test_uv_lock_keeps_named_sources_and_third_party_auth(monkeypatch, tmp_path):
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    project = """[project]
name = "demo"
version = "1.0"
[[tool.uv.index]]
name = "vendor"
url = "https://vendor.test/simple"
explicit = true
[tool.uv.sources]
demo = {index = "vendor"}
"""
    (tmp_path / "pyproject.toml").write_text(project)
    monkeypatch.setenv("UV_INDEX_VENDOR_PASSWORD", "vendor-secret")
    calls = []
    _capture_run(monkeypatch, calls)
    result = runner.invoke(app, ["uv", "--rvs-target", "staging/repo", "lock"])
    assert result.exit_code == 0, result.output
    assert "Additional native sources" in result.output
    assert calls[0]["cmd"] == ["/bin/uv", "lock"]
    assert calls[0]["env"]["UV_INDEX_VENDOR_PASSWORD"] == "vendor-secret"
    assert (tmp_path / "pyproject.toml").read_text() == project
    assert not (tmp_path / "uv.lock").exists()  # mocked native tool creates nothing


def test_uv_read_only_mirror_does_not_request_upload_url(monkeypatch, tmp_path):
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    monkeypatch.setattr(
        native_runner,
        "_resolve_route",
        lambda *a, **kw: native_runner.RegistryRoute(
            "pypi", PYPI_MIRROR_URL, None, "o", "pypiorg", "download-token"
        ),
    )
    calls = []
    _capture_run(monkeypatch, calls)
    result = runner.invoke(app, ["uv", "--rvs-target", "mirror:pypiorg", "lock"])
    assert result.exit_code == 0, result.output
    assert calls[0]["env"]["UV_DEFAULT_INDEX"] == f"{PYPI_MIRROR_URL}/o/pypiorg/simple/"
    assert "UV_PUBLISH_PASSWORD" not in calls[0]["env"]


def test_pip_preserves_extra_index_and_existing_netrc(monkeypatch, tmp_path):
    import netrc

    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    original = tmp_path / "original-netrc"
    content = 'machine vendor.test login vendor password "vendor password"\n'
    original.write_text(content)
    monkeypatch.setenv("NETRC", str(original))
    monkeypatch.setenv("PIP_EXTRA_INDEX_URL", "https://vendor.test/simple/")
    captured = []

    def hook(cmd, env):
        parsed = netrc.netrc(env["NETRC"])
        assert parsed.authenticators("vendor.test") == ("vendor", "", "vendor password")
        assert parsed.authenticators(PYPI_READ_HOST) == (
            "__token__",
            "",
            "rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        )
        assert parsed.authenticators("unrelated.test") is None
        captured.append(env["NETRC"])

    calls = []
    _capture_run(monkeypatch, calls, hook)
    result = runner.invoke(app, ["pip", "--rvs-target", "staging/repo", "install", "demo"])
    assert result.exit_code == 0, result.output
    assert "pip combines candidates" in result.output
    assert calls[0]["env"]["PIP_EXTRA_INDEX_URL"] == "https://vendor.test/simple/"
    assert original.read_text() == content
    assert not Path(captured[0]).exists()


def test_npm_preserves_foreign_scope_and_injects_only_selected_auth(monkeypatch, tmp_path):
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    content = (
        "@vendor:registry=https://vendor.test/npm/\n//vendor.test/npm/:_authToken=vendor-secret\n"
    )
    (tmp_path / ".npmrc").write_text(content)
    calls = []
    _capture_run(monkeypatch, calls)
    result = runner.invoke(app, ["npm", "--rvs-target", "staging/repo", "install", "@vendor/demo"])
    assert result.exit_code == 0, result.output
    assert "Additional native sources" in result.output
    assert (tmp_path / ".npmrc").read_text() == content
    injected = {
        k: v
        for k, v in calls[0]["env"].items()
        if v == "rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    }
    assert injected == {
        f"NPM_CONFIG_//{NPM_READ_HOST}/staging/repo/:_authToken": "rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    }


def test_maven_preserves_other_repositories_and_mirror_credentials(monkeypatch, tmp_path):
    import xml.etree.ElementTree as ET

    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    original = tmp_path / "settings.xml"
    content = """<settings><mirrors><mirror><id>vendor</id><url>https://vendor.test/maven/</url>
<mirrorOf>*</mirrorOf></mirror></mirrors><servers><server><id>vendor</id>
<username>vendor</username><password>vendor-secret</password></server></servers></settings>"""
    original.write_text(content)
    calls = []

    def hook(cmd, env):
        root = ET.parse(cmd[cmd.index("--settings") + 1]).getroot()
        mirrors = {el.findtext("id"): el for el in root.findall("./mirrors/mirror")}
        assert mirrors["vendor"].findtext("url") == "https://vendor.test/maven/"
        assert mirrors["vendor"].findtext("mirrorOf") == "*,!central,!rvs-private"
        assert mirrors["rvs-private"].findtext("mirrorOf") == "central"
        passwords = {
            el.findtext("id"): el.findtext("password") for el in root.findall("./servers/server")
        }
        assert passwords == {
            "vendor": "vendor-secret",
            "rvs-private": "rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        }

    _capture_run(monkeypatch, calls, hook)
    result = runner.invoke(
        app, ["mvn", "--rvs-target", "staging/repo", "-s", str(original), "verify"]
    )
    assert result.exit_code == 0, result.output
    assert "Existing Maven mirrors" in result.output
    assert original.read_text() == content
