from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rvn import config as cfg_mod
from rvn.cli import app
from rvn.native import runner as native_runner
from typer.testing import CliRunner


if TYPE_CHECKING:
    from collections.abc import Callable


runner = CliRunner()
STAGING_API_URL = "https://staging.example.test"
STAGING_HOST = "staging.example.test"


class _Completed:
    returncode = 0


def _isolate_config(monkeypatch: Any, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvn"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text(
        f"""
default_profile = "staging"

[profiles.staging]
api_url = "{STAGING_API_URL}"
customer_id = "cus_staging"
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
    monkeypatch.setenv("RVN_TOKEN", "secret-token")


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


def test_native_npm_respects_project_npmrc_and_injects_path_scoped_auth(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    (tmp_path / ".npmrc").write_text(
        f"@acme:registry={STAGING_API_URL}/npm/x/custpid1/repo-npm/\n",
        encoding="utf-8",
    )
    calls: list[dict[str, Any]] = []
    _capture_run(monkeypatch, calls)

    result = runner.invoke(app, ["npm", "install", "@acme/widgets"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == ["/bin/npm", "install", "@acme/widgets"]
    assert "NPM_CONFIG_REGISTRY" not in calls[0]["env"]
    assert (
        calls[0]["env"][f"NPM_CONFIG_//{STAGING_HOST}/npm/x/custpid1/repo-npm/:_authToken"]
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

    result = runner.invoke(app, ["npm", "--rvn-repo", "repo-npm", "publish"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == [
        "/bin/npm",
        "publish",
        "--registry",
        f"{STAGING_API_URL}/native/npm/x/custpid1/repo-npm/",
    ]
    assert calls[0]["env"]["NPM_CONFIG_REGISTRY"] == (
        f"{STAGING_API_URL}/native/npm/x/custpid1/repo-npm/"
    )
    assert (
        calls[0]["env"][
            f"NPM_CONFIG_//{STAGING_HOST}/native/npm/x/custpid1/repo-npm/:_authToken"
        ]
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
            "--rvn-repo",
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
        f"{STAGING_API_URL}/npm/x/custpid1/repo-npm/",
        "@acme/widgets",
    ]


def test_native_pip_respects_existing_index_and_injects_temp_netrc(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    monkeypatch.setenv("PIP_INDEX_URL", f"{STAGING_API_URL}/pypi/x/custpid1/repo-pypi/simple/")
    calls: list[dict[str, Any]] = []
    netrc_texts: list[str] = []

    def hook(_cmd: list[str], env: dict[str, str]) -> None:
        netrc_texts.append(Path(env["NETRC"]).read_text(encoding="utf-8"))

    _capture_run(monkeypatch, calls, hook)

    result = runner.invoke(app, ["pip", "install", "demo"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == ["/bin/pip", "install", "demo"]
    assert calls[0]["env"]["PIP_INDEX_URL"] == (
        f"{STAGING_API_URL}/pypi/x/custpid1/repo-pypi/simple/"
    )
    assert netrc_texts == [f"machine {STAGING_HOST} login __token__ password secret-token\n"]


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
            "--rvn-repo",
            "repo-pypi",
            "--rvn-native-config",
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
        f"{STAGING_API_URL}/pypi/x/custpid1/repo-pypi/simple/",
        "demo",
    ]
    assert calls[0]["env"]["PIP_CONFIG_FILE"] == os.devnull
    assert netrc_texts == [f"machine {STAGING_HOST} login __token__ password secret-token\n"]


def test_native_pip_preserves_multi_part_pip_command_prefix(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _mock_native_tools(monkeypatch)
    monkeypatch.setattr(native_runner.tools, "pip_cmd", lambda: ["/bin/python", "-m", "pip"])
    calls: list[dict[str, Any]] = []
    _capture_run(monkeypatch, calls)

    result = runner.invoke(app, ["pip", "--rvn-repo", "repo-pypi", "install", "demo"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == [
        "/bin/python",
        "-m",
        "pip",
        "install",
        "--index-url",
        f"{STAGING_API_URL}/pypi/x/custpid1/repo-pypi/simple/",
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

    result = runner.invoke(app, ["uv", "--rvn-repo", "repo-pypi", "sync", "--locked"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == ["/bin/uv", "sync", "--locked"]
    assert calls[0]["env"]["UV_DEFAULT_INDEX"] == (
        f"{STAGING_API_URL}/pypi/x/custpid1/repo-pypi/simple/"
    )
    assert calls[0]["env"]["UV_PUBLISH_URL"] == (
        f"{STAGING_API_URL}/native/pypi/x/custpid1/repo-pypi/"
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

    result = runner.invoke(app, ["twine", "--rvn-repo", "repo-pypi", "upload", "dist/demo.whl"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == ["/bin/twine", "upload", "dist/demo.whl"]
    assert calls[0]["env"]["TWINE_REPOSITORY_URL"] == (
        f"{STAGING_API_URL}/native/pypi/x/custpid1/repo-pypi/"
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

    result = runner.invoke(app, ["mvn", "--rvn-repo", "repo-maven", "deploy"])

    assert result.exit_code == 0
    assert calls[0]["cmd"][0:2] == ["/bin/mvn", "--settings"]
    assert calls[0]["cmd"][-1] == (
        f"-DaltDeploymentRepository=rvn-private::default::{STAGING_API_URL}/native/maven/x/custpid1/repo-maven/"
    )
    assert "<id>rvn-private</id>" in settings_texts[0]
    assert "<username>__token__</username>" in settings_texts[0]
    assert "<password>secret-token</password>" in settings_texts[0]
