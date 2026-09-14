from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

import pytest
import yaml


POSTINSTALL = Path(__file__).parents[1] / "packaging" / "scripts" / "postinstall.sh"
INSTALLER = Path(__file__).parents[1] / "packaging" / "install.sh"
WINDOWS_INSTALLER = Path(__file__).parents[1] / "packaging" / "install.ps1"
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


@pytest.mark.skipif(os.name == "nt", reason="Debian postinstall is POSIX-only")
def test_postinstall_is_silent_without_rocm_rvs(tmp_path: Path) -> None:
    result = _run_postinstall(tmp_path)

    assert result.stdout == ""


@pytest.mark.parametrize(
    "relative_path",
    ("rocm/bin/rvs", "rocm/extras-7/bin/rvs", "rocm-7.2.0/bin/rvs"),
)
@pytest.mark.skipif(os.name == "nt", reason="Debian postinstall is POSIX-only")
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


def test_arm64_public_apt_gate_materializes_its_local_keyring() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    arm64_gate = workflow.split("  verify-apt-arm64:\n", 1)[1].split("\n  deploy-installer:", 1)[0]

    prepare = "run: packaging/repository/prepare_keyring.sh"
    keyring_mount = (
        "packaging/repository/keys/ravenstash-rvs.gpg:/usr/share/keyrings/ravenstash-rvs.gpg:ro"
    )
    assert prepare in arm64_gate
    assert keyring_mount in arm64_gate
    assert arm64_gate.index(prepare) < arm64_gate.index(keyring_mount)


def test_debian_package_installs_node_signature_verifier() -> None:
    manifest = (ROOT / "packaging" / "scripts" / "build-deb.sh").read_text(encoding="utf-8")

    assert "Depends: ca-certificates, gpgv" in manifest
    assert '"$STAGING/usr/bin/docker-credential-rvs"' in manifest


def test_frozen_bundle_dispatches_docker_credential_helper() -> None:
    entrypoint = (ROOT / "packaging" / "pyinstaller" / "entrypoint.py").read_text(encoding="utf-8")
    build = (ROOT / "packaging" / "scripts" / "build-pyinstaller.sh").read_text(encoding="utf-8")

    assert 'Path(sys.argv[0]).stem == "docker-credential-rvs"' in entrypoint
    assert "dist/pyinstaller/rvs/docker-credential-rvs" in build


def test_installer_is_owned_by_cli_packaging_and_pins_release_identity() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    major, minor, _patch = version.split(".", 2)
    channel = f"v0.{minor}" if major == "0" else f"v{major}"

    if os.name != "nt":
        assert INSTALLER.stat().st_mode & 0o111
    assert "https://releases.ravenstash.com/rvs/apt" in source
    assert f'readonly release_version="{version}"' in source
    assert f'readonly compatibility_channel="{channel}"' in source
    assert "3B7C20FC370D1A7C813DF3A2E9679F951AD8BAA0" in source
    assert "--proto '=https' --proto-redir '=https' --tlsv1.2" in source

    windows_source = WINDOWS_INSTALLER.read_text(encoding="utf-8")
    assert f'$ReleaseVersion = "{version}"' in windows_source
    assert f'$CompatibilityChannel = "{channel}"' in windows_source
    assert "Get-FileHash -Algorithm SHA256" in windows_source
    assert "Get-AuthenticodeSignature" not in windows_source
    assert "RVS_GITHUB_TOKEN" in windows_source


def test_installer_prints_ravenstash_banner_after_success() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    assert "RVS_INSTALL_NO_BANNER" in source
    assert "█████████████████████████▄▄▄" in source
    assert "CLI installed successfully" in source
    assert 'print_success_banner\nsay "next: rvs auth login"' in source


def test_apt_installer_redirects_managed_portable_links() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    assert "reconcile_legacy_portable_links()" in source
    assert 'install_root="${HOME}/.local/share/rvs"' in source
    assert '"${install_root}/"*/"${command_name}")' in source
    assert 'ln -sfn "/usr/bin/${command_name}" "$link_path"' in source
    assert "reconcile_legacy_portable_links\n" in source
    assert "was not installed by Ravenstash and may shadow" in source


def test_package_manager_manifests_cover_both_desktop_architectures(tmp_path: Path) -> None:
    release = tmp_path / "release"
    release.mkdir()
    for name in (
        "rvs-v0.12.0-macos-amd64.tar.gz",
        "rvs-v0.12.0-macos-arm64.tar.gz",
        "rvs-v0.12.0-windows-amd64.zip",
        "rvs-v0.12.0-windows-arm64.zip",
    ):
        (release / name).write_bytes(name.encode())

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "packaging/scripts/generate_package_manifests.py"),
            str(release),
            "0.12.0",
            "rvstash/ravenstash-cli-alpha",
        ],
        check=True,
    )

    archive = release / "rvs-v0.12.0-package-manifests.tar.gz"
    with tarfile.open(archive) as package:
        names = package.getnames()
        installer = package.extractfile(
            "package-manifests/winget/Ravenstash.rvs.v0.12.installer.yaml"
        )
        assert installer is not None
        installer_text = installer.read().decode()
        for name in names:
            if name.endswith(".yaml"):
                manifest = package.extractfile(name)
                assert manifest is not None
                assert isinstance(yaml.safe_load(manifest), dict)
        cask = package.extractfile("package-manifests/homebrew/rvs@0.12.rb")
        assert cask is not None
        cask_text = cask.read().decode()
    assert "package-manifests/homebrew/rvs@0.12.rb" in names
    assert "Architecture: x64" in installer_text
    assert "Architecture: arm64" in installer_text
    assert "ravenstash-cli-alpha/releases/download/v0.12.0" in installer_text
    assert 'arch arm: "arm64", intel: "amd64"' in cask_text
