from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

from rvs.entrypoint import _version_requested


if TYPE_CHECKING:
    from pathlib import Path


def test_only_standalone_version_flags_take_the_fast_path() -> None:
    assert _version_requested(["--version"])
    assert _version_requested(["-V"])
    assert not _version_requested([])
    assert not _version_requested(["--json", "--version"])
    assert not _version_requested(["pip", "--version"])


def test_version_fast_path_does_not_import_cli() -> None:
    code = """
import sys
sys.argv = ["rvs", "--version"]
from rvs.entrypoint import main
main()
assert "rvs.cli" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("Ravenstash CLI ")


def test_invalid_config_is_reported_without_a_traceback(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text("config_version = 999\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "rvs.entrypoint", "profile", "current"],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ | {"RVS_HOME": str(tmp_path)},
    )

    stderr = " ".join(result.stderr.split())
    assert result.returncode == 1
    assert result.stdout == ""
    assert "config version 999 is not supported (this release requires version 6)" in stderr
    assert "rvs profile delete --all" in stderr
    assert "Traceback" not in stderr


def test_malformed_config_is_reported_without_a_traceback(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text("profiles = [\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "rvs.entrypoint", "profile", "current"],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ | {"RVS_HOME": str(tmp_path)},
    )

    stderr = " ".join(result.stderr.split())
    assert result.returncode == 1
    assert result.stdout == ""
    assert "could not read" in stderr
    assert "rvs profile delete --all" in stderr
    assert "Traceback" not in stderr
