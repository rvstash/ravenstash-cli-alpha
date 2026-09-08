from __future__ import annotations

import io
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

import pytest
from rvs import config as cfg_mod
from rvs.cli import app
from rvs.oci import credential_helper
from rvs.oci import runner as oci_runner
from typer.testing import CliRunner


runner = CliRunner()


def test_friendly_oci_root_normalizes_display_case_without_changing_identity() -> None:
    assert oci_runner._friendly_oci_root("AcmeHQ", "images") == "acmehq/images"
    assert oci_runner._friendly_oci_root("Acme-HQ", "images") == "acme-hq/images"
    assert oci_runner._friendly_oci_root("Engineering", "Images") == "engineering/images"
    assert oci_runner._friendly_oci_root("Engineering", "IMAGES") == "engineering/images"
    assert oci_runner._stable_oci_root("in_abcdefgh", "r_xyzabcde") == "in_abcdefgh/r_xyzabcde"


class _Response:
    def __init__(self, value: Any) -> None:
        self.value = value

    def json(self) -> Any:
        return self.value


class _Api:
    def get(self, path: str, params=None) -> _Response:
        assert path == "/repositories/resolve"
        if params.get("registry_kind") is None:
            assert "registry_kind" not in params
        else:
            assert params["registry_kind"] in {"container", "helm"}
        assert params["customer_id"] == "customer-1"
        return _Response(
            {
                "customer": {"customer_id": "customer-1"},
                "repository": {
                    "repository_name": "images",
                    "namespace_name": "main",
                    "namespace_realm": "internal",
                    "namespace_unique_ref": "in_abcdefgh",
                    "repository_unique_ref": "r_xyzabcde",
                },
            }
        )

    def post(self, path: str, json=None) -> _Response:
        assert path == "/package-credentials"
        assert json["operations"] in (["download"], ["download", "upload"])
        assert json["expected_target"] == {
            "namespace_unique_ref": "in_abcdefgh",
            "namespace_name": "main",
            "namespace_realm": "internal",
            "repository_unique_ref": "r_xyzabcde",
            "repository_name": "images",
        }
        return _Response(
            {
                "access_token": "exact-secret-capability",
                "native_path": "/main/images",
                "namespace_unique_ref": "in_abcdefgh",
                "repository_unique_ref": "r_xyzabcde",
                "namespace_name": "main",
                "repository_name": "images",
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
customer_id = "customer-1"
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


@pytest.mark.parametrize(
    "tool,args",
    [
        ("docker", ["push", "oci.rvsta.sh/main/images/backend:latest"]),
        ("helm", ["push", "chart.tgz", "oci://oci.rvsta.sh/main/images"]),
        (
            "oras",
            [
                "--rvs-kind",
                "container",
                "push",
                "oci.rvsta.sh/main/images/backend:latest",
                "demo.txt",
            ],
        ),
    ],
)
def test_oci_publish_decline_does_not_launch(monkeypatch, tmp_path: Path, tool, args) -> None:
    _setup(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(oci_runner.subprocess, "Popen", lambda *args, **kwargs: calls.append(args))
    result = runner.invoke(app, [tool, "--rvs-target", "main/images", *args], input="\n")
    assert result.exit_code != 0
    assert "Publish to main/images (personal)" in result.output
    assert not calls


@pytest.mark.parametrize("root", ["main/images", "Main/Images"])
def test_docker_uses_exact_ephemeral_helper_without_secret_in_argv(
    monkeypatch, tmp_path: Path, root
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
            root,
            "push",
            f"oci.rvsta.sh/{root}/backend:Latest",
        ],
        input="y\n",
    )

    assert result.exit_code == 0, result.output
    assert captured["cmd"] == [
        "/usr/bin/docker",
        "push",
        "oci.rvsta.sh/main/images/backend:Latest",
    ]
    assert "exact-secret-capability" not in " ".join(captured["cmd"])
    assert not Path(captured["env"]["RVS_OCI_CREDENTIAL_FILE"]).exists()


def test_namespace_target_accepts_current_friendly_native_root(monkeypatch, tmp_path: Path) -> None:
    _setup(monkeypatch, tmp_path)

    class StablePathApi(_Api):
        def post(self, path: str, json=None) -> _Response:
            response = super().post(path, json)
            response.value["native_path"] = "/in_abcdefgh/r_xyzabcde"
            return response

    monkeypatch.setattr(
        oci_runner.ApiClient,
        "from_profile",
        staticmethod(lambda profile=None: StablePathApi()),
    )

    route = oci_runner.resolve_route(
        "docker",
        oci_runner.OciOptions(target="main/images"),
        ("download", "upload"),
    )

    assert route.native_root == "oci.rvsta.sh/in_abcdefgh/r_xyzabcde"
    assert route.accepted_roots == frozenset({"main/images", "in_abcdefgh/r_xyzabcde"})


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
            "oci.rvsta.sh/in_abcdefgh/r_xyzabcde/backend:latest",
            "--rvs-yes",
        ],
    )

    assert result.exit_code == 128 + signal.SIGTERM
    assert captured["signals"] == [signal.SIGTERM]
    assert not captured["broker"].exists()


@pytest.mark.parametrize("other_root", ["in_abcdefgh/r_23456789", "Main/Other"])
def test_oras_requires_kind_and_rejects_second_ravenstash_target(
    monkeypatch, tmp_path: Path, other_root
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
            f"oci.rvsta.sh/{other_root}/b:two",
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


def test_oci_reference_prints_stable_root_without_v2(monkeypatch, tmp_path: Path) -> None:
    _setup(monkeypatch, tmp_path)

    class StablePathApi(_Api):
        def post(self, path: str, json=None) -> _Response:
            response = super().post(path, json)
            response.value["native_path"] = "/in_abcdefgh/r_xyzabcde"
            return response

    monkeypatch.setattr(
        oci_runner.ApiClient,
        "from_profile",
        staticmethod(lambda profile=None: StablePathApi()),
    )
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
    assert result.output.strip() == ("oci.rvsta.sh/in_abcdefgh/r_xyzabcde/team/api:1.2.3")
    assert "/v2/" not in result.output


def test_oci_capability_rejects_noncanonical_native_path(monkeypatch, tmp_path: Path) -> None:
    _setup(monkeypatch, tmp_path)

    class InvalidPathApi(_Api):
        def post(self, path: str, json=None) -> _Response:
            assert path == "/package-credentials"
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
            "art",
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
        ["art", "mirror", "create", "--registry-kind", "helm"],
    )

    assert package.exit_code != 0
    assert remote.exit_code != 0
    assert "Use rvs docker, rvs helm, or rvs oras" in package.output
    assert "Use rvs docker, rvs helm, or rvs oras" in remote.output


@pytest.mark.parametrize("command", [["push"], ["image", "push"]])
def test_short_push_tags_exact_source_before_push(monkeypatch, tmp_path, command):
    _setup(monkeypatch, tmp_path)
    identity = "sha256:" + "a" * 64
    inspections = []
    launches = []
    destination = "oci.rvsta.sh/main/images/team/api:RC1"

    def inspect(cmd, **kwargs):
        inspections.append(cmd)
        assert "RVS_TOKEN" not in kwargs["env"]
        if cmd[-1] == "team/api:RC1":
            return oci_runner.subprocess.CompletedProcess(cmd, 0, identity + "\n", "")
        assert cmd[-1] == destination
        return oci_runner.subprocess.CompletedProcess(
            cmd, 1, "", "Error: No such image: " + destination
        )

    monkeypatch.setattr(oci_runner.subprocess, "run", inspect)
    monkeypatch.setattr(oci_runner, "_run_process", lambda cmd, env: launches.append((cmd, env)))
    result = runner.invoke(
        app,
        [
            "docker",
            "--rvs-target",
            "main/images",
            "--context",
            "remote",
            *command,
            "--platform=linux/arm64",
            "team/api:RC1",
        ],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    assert len(inspections) == 2
    assert all(cmd[1:3] == ["--context", "remote"] for cmd in inspections)
    assert launches[0][0] == [
        "/usr/bin/docker",
        "--context",
        "remote",
        "image",
        "tag",
        "team/api:RC1",
        destination,
    ]
    assert launches[1][0] == [
        "/usr/bin/docker",
        "--context",
        "remote",
        *command,
        "--platform=linux/arm64",
        destination,
    ]
    assert destination in result.output
    assert not Path(launches[0][1]["RVS_OCI_CREDENTIAL_FILE"]).exists()


@pytest.mark.parametrize(
    "failure", ["collision", "missing-source", "daemon", "tag-failure", "push-failure", "decline"]
)
def test_short_push_failure_does_not_push_wrong_image(monkeypatch, tmp_path, failure):
    _setup(monkeypatch, tmp_path)
    launches = []
    inspections = []

    def inspect(cmd, **kwargs):
        inspections.append(cmd)
        if failure == "missing-source":
            return oci_runner.subprocess.CompletedProcess(cmd, 1, "", "No such image: api:latest")
        if len(inspections) == 2 and failure == "daemon":
            return oci_runner.subprocess.CompletedProcess(
                cmd, 1, "", "Cannot connect to Docker daemon"
            )
        letter = "b" if len(inspections) == 2 and failure == "collision" else "a"
        return oci_runner.subprocess.CompletedProcess(cmd, 0, "sha256:" + letter * 64, "")

    def launch(cmd, env):
        launches.append(cmd)
        if failure == "tag-failure" or (failure == "push-failure" and len(launches) == 2):
            import typer

            raise typer.Exit(17)

    monkeypatch.setattr(oci_runner.subprocess, "run", inspect)
    monkeypatch.setattr(oci_runner, "_run_process", launch)
    result = runner.invoke(
        app,
        ["docker", "--rvs-target", "main/images", "push", "api"],
        input="n\n" if failure == "decline" else "y\n",
    )
    assert result.exit_code != 0
    if failure in {"collision", "missing-source", "daemon", "decline"}:
        assert not launches
    if failure == "decline":
        assert not inspections
    if failure == "tag-failure":
        assert len(launches) == 1
        assert result.exit_code == 17
    if failure == "push-failure":
        assert len(launches) == 2
        assert "retained if push fails" in result.output
        assert result.exit_code == 17


def test_short_pull_uses_saved_target_without_local_alias(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    selected = runner.invoke(app, ["art", "select", "main/images"])
    assert selected.exit_code == 0, selected.output
    launches = []
    monkeypatch.setattr(oci_runner, "_run_process", lambda cmd, env: launches.append(cmd))
    monkeypatch.setattr(
        oci_runner.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("No local tagging on pull"),
    )
    result = runner.invoke(app, ["docker", "image", "pull", "--", "team/api"])
    assert result.exit_code == 0, result.output
    assert launches == [
        ["/usr/bin/docker", "image", "pull", "oci.rvsta.sh/main/images/team/api:latest"]
    ]


def test_short_tag_keeps_source_from_another_repo_local(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    source = "oci.rvsta.sh/other/repo/api:dev"
    identity = "sha256:" + "a" * 64
    inspections = []
    launches = []

    def inspect(cmd, **kwargs):
        inspections.append(cmd[-1])
        return oci_runner.subprocess.CompletedProcess(cmd, 0, identity, "")

    monkeypatch.setattr(oci_runner.subprocess, "run", inspect)
    monkeypatch.setattr(oci_runner, "_run_process", lambda cmd, env: launches.append(cmd))
    result = runner.invoke(
        app, ["docker", "--rvs-target", "main/images", "image", "tag", source, "api:release"]
    )
    assert result.exit_code == 0, result.output
    assert inspections[0] == source
    assert launches == [
        ["/usr/bin/docker", "image", "tag", source, "oci.rvsta.sh/main/images/api:release"]
    ]


def test_docker_explicit_config_preserves_context_plugins_and_buildx(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    native = tmp_path / "docker-config"
    native.mkdir()
    original = '{"currentContext":"remote","auths":{"docker.io":{"auth":"existing"}}}'
    (native / "config.json").write_text(original)
    for directory in ("contexts", "cli-plugins", "buildx"):
        (native / directory).mkdir()
        (native / directory / "sentinel").write_text(directory)
    monkeypatch.delenv("BUILDX_CONFIG", raising=False)
    seen = []

    def launch(cmd, env):
        seen.append(cmd)
        overlay = Path(env["DOCKER_CONFIG"])
        assert overlay != native
        data = json.loads((overlay / "config.json").read_text())
        assert data["currentContext"] == "remote"
        assert data["auths"]["docker.io"]["auth"] == "existing"
        assert data["credHelpers"]["oci.rvsta.sh"] == "rvs"
        for directory in ("contexts", "cli-plugins"):
            assert (overlay / directory / "sentinel").read_text() == directory
        assert env["BUILDX_CONFIG"] == str(native / "buildx")

    monkeypatch.setattr(oci_runner, "_run_process", launch)
    result = runner.invoke(
        app, ["docker", "--rvs-target", "main/images", f"--config={native}", "pull", "api"]
    )
    assert result.exit_code == 0, result.output
    assert seen == [["/usr/bin/docker", "pull", "oci.rvsta.sh/main/images/api:latest"]]
    assert (native / "config.json").read_text() == original


@pytest.mark.parametrize(
    "arguments,tail",
    [
        (
            ["pull", "api", "--version", "1.2.3"],
            ["pull", "oci://oci.rvsta.sh/main/images/api", "--version", "1.2.3"],
        ),
        (["--rvs-yes", "push", "api.tgz"], ["push", "api.tgz", "oci://oci.rvsta.sh/main/images"]),
        (
            ["--rvs-yes", "push", "--plain-http", "api.tgz"],
            ["push", "--plain-http", "api.tgz", "oci://oci.rvsta.sh/main/images"],
        ),
    ],
)
def test_helm_saved_target_shorthand_uses_temporary_config(monkeypatch, tmp_path, arguments, tail):
    _setup(monkeypatch, tmp_path)
    assert runner.invoke(app, ["art", "select", "main/images"]).exit_code == 0
    source = tmp_path / "helm.json"
    source.write_text('{"auths":{"public.example":{"auth":"public-auth"}}}')
    captured = []

    def run_process(argv, env):
        captured.append(argv)
        config_path = Path(env["HELM_REGISTRY_CONFIG"])
        assert config_path != source
        config = json.loads(config_path.read_text())
        assert config["auths"]["public.example"]["auth"] == "public-auth"
        assert config["credHelpers"]["oci.rvsta.sh"] == "rvs"
        assert "--registry-config" not in argv
        assert "exact-secret-capability" not in " ".join(argv)

    publish_arguments = []
    native_artifacts = oci_runner.oci_artifacts

    def artifacts(tool, argv, host):
        publish_arguments.append(argv)
        return native_artifacts(tool, argv, host)

    monkeypatch.setattr(oci_runner, "oci_artifacts", artifacts)
    monkeypatch.setattr(oci_runner, "_run_process", run_process)
    result = runner.invoke(app, ["helm", "--registry-config", str(source), *arguments])
    assert result.exit_code == 0, result.output
    assert captured == [["/usr/bin/helm", *tail]]
    if "push" in arguments:
        assert publish_arguments == [["push", "api.tgz", "oci://oci.rvsta.sh/main/images"]]
    assert source.read_text() == '{"auths":{"public.example":{"auth":"public-auth"}}}'
