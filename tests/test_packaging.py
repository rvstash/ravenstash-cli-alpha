from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


POSTINSTALL = Path(__file__).parents[1] / "packaging" / "scripts" / "postinstall.sh"
INSTALLER = Path(__file__).parents[1] / "packaging" / "install.sh"
ROOT = Path(__file__).parents[1]


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


def test_release_metadata_uses_mit_license() -> None:
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License\n")
    assert 'license = "MIT"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_apt_repository_script_exports_installable_public_key() -> None:
    script = (ROOT / "packaging" / "scripts" / "update-apt-repo.sh").read_text(encoding="utf-8")

    assert '--export "$RVS_APT_GPG_KEY_ID"' in script
    assert '"${APT_REPO_DIR}/ravenstash-rvs.gpg"' in script


def test_debian_package_installs_node_signature_verifier() -> None:
    manifest = (ROOT / "packaging" / "scripts" / "build-deb.sh").read_text(encoding="utf-8")

    assert "Depends: ca-certificates, gpgv" in manifest
    assert '"$STAGING/usr/bin/docker-credential-rvs"' in manifest


def test_frozen_bundle_dispatches_docker_credential_helper() -> None:
    entrypoint = (ROOT / "packaging" / "pyinstaller" / "entrypoint.py").read_text(encoding="utf-8")
    build = (ROOT / "packaging" / "scripts" / "build-pyinstaller.sh").read_text(encoding="utf-8")

    assert 'Path(sys.argv[0]).name == "docker-credential-rvs"' in entrypoint
    assert "dist/pyinstaller/rvs/docker-credential-rvs" in build


def test_installer_is_owned_by_cli_packaging_and_pins_release_identity() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    assert INSTALLER.stat().st_mode & 0o111
    assert "https://releases.ravenstash.com/rvs/apt" in source
    assert 'readonly compatibility_channel="v0.5"' in source
    assert "3B7C20FC370D1A7C813DF3A2E9679F951AD8BAA0" in source
    assert "--proto '=https' --proto-redir '=https' --tlsv1.2" in source
