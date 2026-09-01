from __future__ import annotations

import io
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

from rvs import config as cfg_mod
from rvs.cli import app
from rvs.oci import credential_helper
from rvs.oci import runner as oci_runner
from typer.testing import CliRunner


runner = CliRunner()


class _Response:
    def __init__(self, value: Any) -> None:
        self.value = value

    def json(self) -> Any:
        return self.value


class _Api:
    def get(self, path: str, params=None) -> _Response:
        assert path == "/v0/repositories/resolve"
        assert params["registry_kind"] in {"container", "helm"}
        assert "customer_id" not in params
        return _Response(
            {
                "customer": {"customer_id": "customer-1"},
                "repository": {
                    "id": "repository-1",
                    "repository_name": "images",
                    "workspace_id": "workspace-1",
                    "workspace_name": "main",
                    "workspace_unique_ref": "w_abcdefgh",
                    "repository_unique_ref": "r_xyzabcde",
                },
            }
        )

    def post(self, path: str, json=None) -> _Response:
        assert path == "/v0/package-credentials"
        assert json["operations"] in (["download"], ["download", "upload"])
        assert json["expected_target"] == {
            "workspace_id": "workspace-1",
            "workspace_unique_ref": "w_abcdefgh",
            "workspace_name": "main",
            "repository_id": "repository-1",
            "repository_unique_ref": "r_xyzabcde",
            "repository_name": "images",
        }
        return _Response(
            {
                "access_token": "exact-secret-capability",
                "native_path": "/main/images",
                "workspace_unique_ref": "w_abcdefgh",
                "repository_unique_ref": "r_xyzabcde",
            }
        )


def test_oci_commands_request_only_the_operations_they_need() -> None:
    assert oci_runner._operations_for("docker", ["pull", "image:tag"]) == ("download",)
    assert oci_runner._operations_for("docker", ["push", "image:tag"]) == (
        "download",
        "upload",
    )
    assert oci_runner._operations_for("helm", ["show", "chart", "oci://chart"]) == ("download",)
    assert oci_runner._operations_for("helm", ["push", "chart.tgz"]) == (
        "download",
        "upload",
    )
    assert oci_runner._operations_for("oras", ["copy", "source", "target"]) == (
        "download",
        "upload",
    )


def _setup(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvs"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text(
        """
default_profile = "default"

[profiles.default]
api_url = "https://api.example.test"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(cfg_mod, "PROFILE_ENV_FILE", config_dir / "profiles.env")
    monkeypatch.setenv("RVS_TOKEN", "raw-control-token")
    monkeypatch.setattr(
        oci_runner.ApiClient, "from_profile", staticmethod(lambda profile=None: _Api())
    )
    monkeypatch.setattr(
        oci_runner.tools,
        "require",
        lambda name, *, install_kind: f"/usr/bin/{name}",
    )


def test_docker_uses_exact_ephemeral_helper_without_secret_in_argv(
    monkeypatch, tmp_path: Path
) -> None:
    _setup(monkeypatch, tmp_path)
    captured: dict[str, Any] = {}

    class FakeProcess:
        def __init__(self, cmd, *, env):
            captured["cmd"] = cmd
            captured["env"] = env.copy()
            assert "RVS_TOKEN" not in env
            broker = Path(env["RVS_OCI_CREDENTIAL_FILE"])
            config = Path(env["DOCKER_CONFIG"]) / "config.json"
            assert broker.stat().st_mode & 0o077 == 0
            assert config.stat().st_mode & 0o077 == 0
            assert json.loads(config.read_text())["credHelpers"] == {"oci.rvsta.sh": "rvs"}
            assert json.loads(broker.read_text())["username"] == "__token__"

        def poll(self):
            return None

        def send_signal(self, _signum):
            raise AssertionError("successful execution must not forward a signal")

        def wait(self):
            return 0

    monkeypatch.setattr(oci_runner.subprocess, "Popen", FakeProcess)
    result = runner.invoke(
        app,
        [
            "docker",
            "--rvs-target",
            "main/images",
            "push",
            "oci.rvsta.sh/main/images/backend:latest",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["cmd"] == [
        "/usr/bin/docker",
        "push",
        "oci.rvsta.sh/main/images/backend:latest",
    ]
    assert "exact-secret-capability" not in " ".join(captured["cmd"])
    assert not Path(captured["env"]["RVS_OCI_CREDENTIAL_FILE"]).exists()


def test_docker_preserves_other_native_credentials_but_replaces_ravenstash(
    monkeypatch, tmp_path: Path
) -> None:
    _setup(monkeypatch, tmp_path)
    docker_config = tmp_path / "native-docker"
    docker_config.mkdir()
    (docker_config / "config.json").write_text(
        json.dumps(
            {
                "auths": {
                    "private.example.test": {"auth": "external-secret"},
                    "https://oci.rvsta.sh/v1/": {"auth": "stale-ravenstash-secret"},
                },
                "credHelpers": {
                    "helpers.example.test": "desktop",
                    "oci.rvsta.sh": "stale-helper",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCKER_CONFIG", str(docker_config))
    captured: dict[str, Any] = {}

    class FakeProcess:
        def __init__(self, _cmd, *, env):
            generated = json.loads((Path(env["DOCKER_CONFIG"]) / "config.json").read_text())
            captured.update(generated)

        def poll(self):
            return None

        def wait(self):
            return 0

    monkeypatch.setattr(oci_runner.subprocess, "Popen", FakeProcess)

    result = runner.invoke(
        app,
        [
            "docker",
            "--rvs-target",
            "main/images",
            "pull",
            "private.example.test/base:1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["auths"] == {"private.example.test": {"auth": "external-secret"}}
    assert captured["credHelpers"] == {
        "helpers.example.test": "desktop",
        "oci.rvsta.sh": "rvs",
    }


def test_native_signal_is_forwarded_with_shell_exit_code_and_secret_cleanup(
    monkeypatch, tmp_path: Path
) -> None:
    _setup(monkeypatch, tmp_path)
    captured: dict[str, Any] = {"signals": []}

    class FakeProcess:
        def __init__(self, _cmd, *, env):
            captured["broker"] = Path(env["RVS_OCI_CREDENTIAL_FILE"])

        def poll(self):
            return None

        def send_signal(self, signum):
            captured["signals"].append(signum)

        def wait(self):
            os.kill(os.getpid(), signal.SIGTERM)
            return -signal.SIGTERM

    monkeypatch.setattr(oci_runner.subprocess, "Popen", FakeProcess)

    result = runner.invoke(
        app,
        [
            "docker",
            "--rvs-target",
            "main/images",
            "push",
            "oci.rvsta.sh/w_abcdefgh/r_xyzabcde/backend:latest",
        ],
    )

    assert result.exit_code == 128 + signal.SIGTERM
    assert captured["signals"] == [signal.SIGTERM]
    assert not captured["broker"].exists()


def test_oras_requires_kind_and_rejects_second_ravenstash_target(
    monkeypatch, tmp_path: Path
) -> None:
    _setup(monkeypatch, tmp_path)
    missing = runner.invoke(app, ["oras", "--rvs-target", "main/images", "discover"])
    assert missing.exit_code != 0

    rejected = runner.invoke(
        app,
        [
            "oras",
            "--rvs-kind",
            "container",
            "--rvs-target",
            "main/images",
            "cp",
            "oci.rvsta.sh/main/images/a:one",
            "oci.rvsta.sh/w_abcdefgh/r_23456789/b:two",
        ],
    )
    assert rejected.exit_code != 0
    assert "another Ravenstash logical repository" in rejected.output


def test_credential_helper_is_exact_host_and_read_only(monkeypatch, tmp_path: Path, capsys) -> None:
    broker = tmp_path / "broker.json"
    broker.write_text(
        json.dumps(
            {
                "server": "oci.rvsta.sh",
                "username": "helm",
                "secret": "ephemeral-secret",
            }
        ),
        encoding="utf-8",
    )
    broker.chmod(0o600)
    monkeypatch.setenv("RVS_OCI_CREDENTIAL_FILE", str(broker))
    monkeypatch.setattr(sys, "argv", ["docker-credential-rvs", "get"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("https://oci.rvsta.sh"))

    credential_helper.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"Username": "helm", "Secret": "ephemeral-secret"}


def test_oci_reference_prints_public_friendly_root_without_v2(monkeypatch, tmp_path: Path) -> None:
    _setup(monkeypatch, tmp_path)
    result = runner.invoke(
        app,
        [
            "oci-reference",
            "--kind",
            "helm",
            "--target",
            "main/charts",
            "--oci-path",
            "team/api",
            "--reference",
            "1.2.3",
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.output.strip() == ("oci.rvsta.sh/main/images/team/api:1.2.3")
    assert "/v2/" not in result.output


def test_oci_capability_rejects_noncanonical_native_path(monkeypatch, tmp_path: Path) -> None:
    _setup(monkeypatch, tmp_path)

    class InvalidPathApi(_Api):
        def post(self, path: str, json=None) -> _Response:
            assert path == "/v0/package-credentials"
            return _Response(
                {
                    "access_token": "exact-secret-capability",
                    "native_path": "/_abcdefgh/_xyzabcde",
                }
            )

    monkeypatch.setattr(
        oci_runner.ApiClient,
        "from_profile",
        staticmethod(lambda profile=None: InvalidPathApi()),
    )

    result = runner.invoke(
        app,
        ["oci-reference", "--kind", "container", "--target", "main/images"],
    )

    assert result.exit_code != 0
    assert "native_path is not canonical" in result.output


def test_package_and_mirror_commands_reject_oci_kinds() -> None:
    package = runner.invoke(
        app,
        [
            "pkg",
            "package",
            "list",
            "--repo",
            "images",
            "--registry-kind",
            "container",
        ],
    )
    remote = runner.invoke(
        app,
        ["pkg", "mirror", "create", "--registry-kind", "helm"],
    )

    assert package.exit_code != 0
    assert remote.exit_code != 0
    assert "Use rvs docker, rvs helm, or rvs oras" in package.output
    assert "Use rvs docker, rvs helm, or rvs oras" in remote.output
