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
    config_file.write_text(content or 'default_profile = "default"\n', encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)


def test_root_help_exposes_clean_alpha_command_surface() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in (
        "pip",
        "uv",
        "twine",
        "npm",
        "mvn",
        "auth",
        "runtime",
        "pkg",
        "packages",
        "repo",
        "ci",
    ):
        assert command in result.output
    for removed_root_command in ("pypi", "maven", "system", "sync", "tokens"):
        assert removed_root_command not in result.output


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

    result = runner.invoke(app, ["--json", "pkg", "repo", "defaults"])
    output.set_json(False)

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["title"] == "Package repository defaults (default)"
    assert payload["items"][0] == {
        "Registry kind": "pypi",
        "Default repository": "private-pypi",
    }


def test_packages_alias_dispatches_to_pkg_commands(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RVS_PROFILE_STAGING_API_URL", STAGING_API_URL)
    monkeypatch.setenv("RVS_PROFILE_STAGING_REPOSITORY_DOMAIN", "packages.example.test")
    _isolate_config(
        monkeypatch,
        tmp_path,
        """
default_profile = "default"

[registries.pypi]
default_repo = "repo-alias"

[profiles.staging]
customer_unique_id = "custpid1"
""".strip(),
    )

    pkg_result = runner.invoke(app, ["pkg", "repo", "defaults", "--profile", "staging"])
    packages_result = runner.invoke(app, ["packages", "repo", "defaults", "--profile", "staging"])

    assert pkg_result.exit_code == 0
    assert packages_result.exit_code == 0
    assert packages_result.output == pkg_result.output
    assert "Package repository defaults" in packages_result.output
    assert "(staging)" in packages_result.output


def test_repo_commands_are_registered() -> None:
    repo_result = runner.invoke(app, ["repo", "--help"])

    assert repo_result.exit_code == 0
    for command in ("list", "create", "show", "rename", "delete"):
        assert command in repo_result.output


def test_registry_kind_is_canonical_and_ecosystem_is_a_compatible_alias() -> None:
    result = runner.invoke(app, ["pkg", "repo", "list", "--help"])

    assert result.exit_code == 0
    help_output = unstyle(result.output)
    assert "--registry-kind" in help_output
    assert "--ecosystem" in help_output


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

    assert ci_result.exit_code == 1
    assert "rvs ci is not implemented yet" in ci_result.stderr
