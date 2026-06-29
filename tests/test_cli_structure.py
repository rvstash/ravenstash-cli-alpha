from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from rvn import config as cfg_mod
from rvn.cli import app
from typer.testing import CliRunner


if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()
STAGING_API_URL = "https://staging.example.test"


def _isolate_config(monkeypatch, tmp_path: Path, content: str = "") -> None:
    config_dir = tmp_path / ".rvn"
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
    assert result.output.startswith("rvn ")


def test_packages_alias_dispatches_to_pkg_commands(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RVN_PROFILE_STAGING_API_URL", STAGING_API_URL)
    _isolate_config(
        monkeypatch,
        tmp_path,
        """
default_profile = "default"

[registries.pypi]
default_repo = "repo-alias"

[profiles.staging]
customer_public_id = "custpid1"
""".strip(),
    )

    pkg_result = runner.invoke(app, ["pkg", "pypi", "index-url", "--profile", "staging"])
    packages_result = runner.invoke(app, ["packages", "pypi", "index-url", "--profile", "staging"])

    assert pkg_result.exit_code == 0
    assert packages_result.exit_code == 0
    assert packages_result.output == pkg_result.output
    assert (
        packages_result.output.strip() == f"{STAGING_API_URL}/n/pypi/x/custpid1/repo-alias/simple/"
    )


@pytest.mark.parametrize(
    "args",
    [
        ["repo", "list"],
        ["repo", "create", "demo"],
        ["repo", "clone", "demo"],
        ["repo", "show", "demo"],
        ["repo", "delete", "demo"],
    ],
)
def test_repo_placeholder_commands_are_registered(args: list[str]) -> None:
    repo_result = runner.invoke(app, args)

    assert repo_result.exit_code == 1
    assert "rvn repo is not implemented yet" in repo_result.stderr


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
    assert "rvn ci is not implemented yet" in ci_result.stderr
