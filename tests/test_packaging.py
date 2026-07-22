from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


POSTINSTALL = Path(__file__).parents[1] / "packaging" / "scripts" / "postinstall.sh"


def _run_postinstall(rocm_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"RAVENSTASH_ROCM_ROOT": str(rocm_root)}
    return subprocess.run(
        [str(POSTINSTALL)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def test_postinstall_is_silent_without_rocm_rvs(tmp_path: Path) -> None:
    result = _run_postinstall(tmp_path)

    assert result.stdout == ""


@pytest.mark.parametrize(
    "relative_path",
    ("rocm/bin/rvs", "rocm/extras-7/bin/rvs", "rocm-7.2.0/bin/rvs"),
)
def test_postinstall_reports_rocm_rvs_and_ravenstash_alias(
    tmp_path: Path, relative_path: str
) -> None:
    rocm_rvs = tmp_path / relative_path
    rocm_rvs.parent.mkdir(parents=True)
    rocm_rvs.write_text("#!/bin/sh\n", encoding="utf-8")
    rocm_rvs.chmod(0o755)

    result = _run_postinstall(tmp_path)

    assert f"AMD ROCm Validation Suite was detected at {rocm_rvs}." in result.stdout
    assert "Both tools provide the 'rvs' shortcut" in result.stdout
    assert "'ravenstash' command" in result.stdout
