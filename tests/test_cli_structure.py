from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from click import unstyle
from rvs import config as cfg_mod
from rvs import output
from rvs.cli import app
from typer.testing import CliRunner


if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()
STAGING_API_URL = "https://control.example.test"


def _isolate_config(monkeypatch, tmp_path: Path, content: str = "") -> None:
    config_dir = tmp_path / ".rvs"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    normalized = content or 'default_profile = "default"\n'
    if "config_version" not in normalized:
        normalized = f"config_version = 5\n{normalized}"
    config_file.write_text(normalized, encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)


def test_root_help_exposes_clean_public_command_surface() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in (
        "pip",
        "uv",
        "twine",
        "npm",
        "mvn",
        "auth",
        "profile",
        "account",
        "context",
        "runtime",
        "art",
    ):
        assert command in result.output
    for removed_root_command in ("pypi", "maven", "system", "sync", "tokens"):
        assert removed_root_command not in result.output
    removed = runner.invoke(app, ["shell", "--help"])
    assert removed.exit_code != 0
    assert "No such command" in removed.output


def test_context_commands_are_separated_from_auth_help() -> None:
    auth_result = runner.invoke(app, ["auth", "--help"])
    profile_result = runner.invoke(app, ["profile", "--help"])
    account_result = runner.invoke(app, ["account", "--help"])

    assert auth_result.exit_code == 0
    assert "Manage named local CLI profiles" not in auth_result.output
    assert "login" in auth_result.output
    assert profile_result.exit_code == 0
    assert "current" in profile_result.output
    assert "use" in profile_result.output
    assert "switch" not in profile_result.output
    assert account_result.exit_code == 0
    assert "use" in account_result.output
    assert "switch" not in account_result.output


def test_root_without_args_shows_help() -> None:
    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "Ravenstash developer CLI" in result.output


def test_version_option_prints_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.startswith("Ravenstash CLI ")


def test_json_option_emits_structured_rvs_output(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(
        monkeypatch,
        tmp_path,
        """
default_profile = "default"

[profiles.default.registries.pypi]
default_repo = "private-pypi"
""".strip(),
    )

    result = runner.invoke(app, ["--json", "art", "repo", "defaults"])
    output.set_json(False)

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["title"] == "Repository defaults (default)"
    assert payload["items"][0] == {
        "format": "pypi",
        "default_repository": "private-pypi",
    }


def test_removed_compatibility_groups_are_rejected() -> None:
    packages_result = runner.invoke(app, ["packages", "--help"])
    keyring_result = runner.invoke(app, ["auth", "keyring", "doctor"])
    cache_result = runner.invoke(app, ["art", "cache", "--help"])
    remote_cache_result = runner.invoke(app, ["art", "remote-cache", "--help"])

    assert packages_result.exit_code != 0
    assert keyring_result.exit_code != 0
    assert cache_result.exit_code != 0
    assert remote_cache_result.exit_code != 0


@pytest.mark.parametrize("command", ["install", "pypi", "npm", "maven"])
def test_artifact_execution_commands_are_removed(command: str) -> None:
    result = runner.invoke(app, ["art", command, "--help"])

    assert result.exit_code != 0
    assert "No such command" in result.output


@pytest.mark.parametrize("alias", ["art"])
def test_repo_commands_are_registered(alias: str) -> None:
    repo_result = runner.invoke(app, [alias, "repo", "--help"])

    assert repo_result.exit_code == 0
    for command in ("list", "create", "show", "rename", "delete"):
        assert command in repo_result.output


@pytest.mark.parametrize("command", ["repo", "pkg"])
def test_retired_top_level_commands_are_removed(command: str) -> None:
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code != 0
    assert "No such command" in result.output


def test_artifact_spellings_share_one_command_application() -> None:
    groups = {group.name: group.typer_instance for group in app.registered_groups}
    assert "art" in groups
    assert "artifacts" not in groups
    assert not {"repo", "pkg"}.intersection(groups)


@pytest.mark.parametrize("alias", ["art"])
def test_artifact_alias_json_has_no_transition_warning(
    monkeypatch, tmp_path: Path, alias: str
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    result = runner.invoke(app, ["--json", alias, "repo", "defaults"])
    output.set_json(False)
    assert result.exit_code == 0
    assert {item["format"] for item in json.loads(result.stdout)["items"]} == {
        "pypi",
        "npm",
        "maven",
        "oci",
    }
    assert "DeprecationWarning" not in result.stderr


def test_registry_kind_has_no_ecosystem_alias() -> None:
    result = runner.invoke(app, ["art", "repo", "list", "--help"])

    assert result.exit_code == 0
    help_output = unstyle(result.output)
    assert "--format" in help_output
    assert "--ecosystem" not in help_output


def test_upstream_commands_call_the_public_positional_argument_format() -> None:
    result = runner.invoke(app, ["art", "repo", "upstream", "add", "--help"])

    assert result.exit_code == 0
    help_output = unstyle(result.output)
    assert "REPOSITORY FORMAT" in help_output
    assert " KIND" not in help_output


def test_repository_group_has_no_legacy_upstream_commands() -> None:
    result = runner.invoke(app, ["art", "repo", "--help"])

    assert result.exit_code == 0
    help_output = unstyle(result.output)
    assert "set-upstream" not in help_output
    assert "clear-upstream" not in help_output


@pytest.mark.parametrize("command", ["pip", "docker"])
def test_native_wrappers_reject_removed_repository_option(command: str) -> None:
    result = runner.invoke(app, [command, "--rvs-repo", "acme/packages", "version"])

    assert result.exit_code != 0
    assert "Use --rvs-target" in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["ci", "list"],
        ["ci", "run"],
        ["ci", "run", "pipeline"],
        ["ci", "status"],
        ["ci", "status", "run_123"],
        ["ci", "logs", "run_123"],
    ],
)
def test_ci_placeholder_commands_are_registered(args: list[str]) -> None:
    ci_result = runner.invoke(app, args)

    assert ci_result.exit_code == 2
    assert "No such command" in ci_result.output
