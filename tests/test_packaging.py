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


def test_parallel_public_apt_gates_materialize_their_local_keyring() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    apt_gate = workflow.split("  verify-apt:\n", 1)[1].split("\n  publish-github-release:", 1)[0]

    prepare = "run: packaging/repository/prepare_keyring.sh"
    keyring_mount = (
        "packaging/repository/keys/ravenstash-rvs.gpg:/usr/share/keyrings/ravenstash-rvs.gpg:ro"
    )
    assert "runner: ubuntu-24.04-arm" in apt_gate
    assert prepare in apt_gate
    assert keyring_mount in apt_gate
    assert apt_gate.index(prepare) < apt_gate.index(keyring_mount)


def test_apt_publisher_batches_architectures_without_weakening_activation_order() -> None:
    publisher = (ROOT / "packaging/repository/publish_apt.sh").read_text(encoding="utf-8")

    assert '--include "*/by-hash/SHA256/*"' in publisher
    assert '--include "*/Packages"' in publisher
    assert '--include "*/InRelease"' in publisher
    assert publisher.index('--include "*/by-hash/SHA256/*"') < publisher.index(
        '--include "*/Packages"'
    )
    assert publisher.index('--include "*/Packages"') < publisher.index('--include "*/InRelease"')
    assert publisher.index('--include "*/InRelease"') < publisher.index(
        '"$repository/channels.json"'
    )


@pytest.mark.skipif(os.name == "nt", reason="APT publication tooling is POSIX-only")
def test_apt_publisher_uses_constant_number_of_storage_calls(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    for channel in ("stable", "v0.3", "v0.13"):
        (repository / "dists" / channel).mkdir(parents=True)
    (repository / "pool").mkdir()
    calls = tmp_path / "aws-calls"
    binary = tmp_path / "bin"
    binary.mkdir()
    aws = binary / "aws"
    aws.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$AWS_CALLS"\n', encoding="utf-8")
    aws.chmod(0o755)

    subprocess.run(
        [
            str(ROOT / "packaging/repository/publish_apt.sh"),
            str(repository),
            "https://r2.example.test",
            "test-bucket",
        ],
        check=True,
        env=os.environ
        | {
            "AWS_CALLS": str(calls),
            "PATH": f"{binary}{os.pathsep}{os.environ['PATH']}",
        },
    )

    assert len(calls.read_text(encoding="utf-8").splitlines()) == 8


def test_release_candidate_keeps_target_handoffs_isolated() -> None:
    candidate_path = ROOT / ".github/workflows/release-candidate.yml"
    candidate = candidate_path.read_text(encoding="utf-8")
    jobs = yaml.safe_load(candidate)["jobs"]
    build_jobs = {name: job for name, job in jobs.items() if "uses" in job}
    artifact_names = [
        Path(path).name
        for job in build_jobs.values()
        for path in job["with"]["artifact_paths"].splitlines()
    ]

    assert "merge-multiple: true" not in candidate
    assert "Download isolated target handoffs" in candidate
    assert 'test "${#matches[@]}" = 1' in candidate
    assert len(build_jobs) == 8
    assert {job["needs"] for job in build_jobs.values()} == {"validate"}
    assert len(artifact_names) == len(set(artifact_names)) == 10
    assert set(jobs["assemble"]["needs"]) == set(build_jobs)


def test_publication_graph_parallelizes_safe_jobs_and_serializes_mutations() -> None:
    publication = yaml.safe_load(
        (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    )
    jobs = publication["jobs"]

    assert "needs" not in jobs["validate-candidate"]
    assert "needs" not in jobs["restore-apt"]
    assert set(jobs["sign"]["needs"]) == {"validate-candidate", "restore-apt"}
    assert jobs["publish-apt"]["needs"] == "sign"
    assert jobs["verify-apt"]["needs"] == "publish-apt"
    assert jobs["verify-apt"]["strategy"]["fail-fast"] is False
    assert len(jobs["verify-apt"]["strategy"]["matrix"]["include"]) == 2
    assert jobs["publish-github-release"]["needs"] == "verify-apt"


def test_publication_consumes_candidate_and_appends_architectures_once() -> None:
    publication = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    append = "packaging/repository/append_and_sign_apt.sh"

    assert "run-id: ${{ inputs.candidate_run_id }}" in publication
    assert publication.count(append) == 1
    assert '"build/rvs_${VERSION}_amd64.deb"' in publication
    assert '"build/rvs_${VERSION}_arm64.deb"' in publication
    assert "  build:" not in publication
    assert "RVS_APT_PROMOTE_CHANNEL" not in publication


def test_successful_publication_is_not_failed_by_best_effort_cleanup() -> None:
    candidate = (ROOT / ".github/workflows/release-candidate.yml").read_text(encoding="utf-8")
    publication = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    promotion = (ROOT / ".github/workflows/promote-installer.yml").read_text(encoding="utf-8")

    assert "Delete only target-specific artifacts\n        continue-on-error: true" in candidate
    assert (
        "Delete current-run handoffs and consumed candidate\n        continue-on-error: true"
        in publication
    )
    assert "Delete temporary promotion artifacts\n        continue-on-error: true" in promotion


def test_publication_refuses_to_replace_an_existing_tag_or_release() -> None:
    publication = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    release_slot = "packaging/scripts/assert-github-release-slot-empty.sh"
    assert publication.count(release_slot) == 2
    assert "gh release upload" not in publication
    assert "--clobber" not in publication


@pytest.mark.parametrize(
    ("mode", "expected_returncode"),
    (("empty", 0), ("tag", 1), ("release", 1), ("api-error", 1)),
)
@pytest.mark.skipif(os.name == "nt", reason="release-slot tooling is POSIX-only")
def test_release_slot_check_fails_closed(
    tmp_path: Path, mode: str, expected_returncode: int
) -> None:
    binary = tmp_path / "bin"
    binary.mkdir()
    gh = binary / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        'case "$GH_MODE:$*" in\n'
        "  api-error:*) exit 1 ;;\n"
        "  tag:*matching-refs*) printf '%s\\n' refs/tags/v0.13.2 ;;\n"
        "  release:*releases*) printf '%s\\n' 1234 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)

    result = subprocess.run(
        [
            str(ROOT / "packaging/scripts/assert-github-release-slot-empty.sh"),
            "rvstash/ravenstash-cli-alpha",
            "v0.13.2",
        ],
        check=False,
        env=os.environ
        | {
            "GH_MODE": mode,
            "PATH": f"{binary}{os.pathsep}{os.environ['PATH']}",
        },
    )

    assert result.returncode == expected_returncode


def test_platform_ci_uses_exact_bundles_and_supplies_musl_bash() -> None:
    platform = (ROOT / ".github/workflows/platform-ci.yml").read_text(encoding="utf-8")

    assert "apk add --no-cache bash binutils build-base libffi-dev" in platform
    assert 'bundle="build/release/rvs-v${version}-${TARGET}"' in platform
    assert "find build/release" not in platform
    assert platform.count('test -d "$bundle"') == 2


def test_channel_recommendation_activates_after_installer_verification() -> None:
    promotion = yaml.safe_load(
        (ROOT / ".github/workflows/promote-installer.yml").read_text(encoding="utf-8")
    )
    jobs = promotion["jobs"]

    assert jobs["promote"]["needs"] == "sign-channel-manifest"
    assert set(jobs["publish-channel-manifest"]["needs"]) == {
        "sign-channel-manifest",
        "promote",
    }


def test_installer_worker_binds_both_public_routes() -> None:
    configuration = (ROOT / "packaging/installer-worker/wrangler.toml").read_text(encoding="utf-8")

    assert 'pattern = "https://ravenstash.com/install.sh*"' in configuration
    assert 'pattern = "https://ravenstash.com/install.ps1*"' in configuration


def test_debian_package_installs_node_signature_verifier() -> None:
    manifest = (ROOT / "packaging" / "scripts" / "build-deb.sh").read_text(encoding="utf-8")

    assert "Depends: ca-certificates, gpgv" in manifest
    assert '"$STAGING/usr/bin/docker-credential-rvs"' in manifest


def test_frozen_bundle_dispatches_docker_credential_helper() -> None:
    entrypoint = (ROOT / "packaging" / "pyinstaller" / "entrypoint.py").read_text(encoding="utf-8")
    shared_entrypoint = (ROOT / "rvs" / "entrypoint.py").read_text(encoding="utf-8")
    build = (ROOT / "packaging" / "scripts" / "build-pyinstaller.sh").read_text(encoding="utf-8")

    assert "from rvs.entrypoint import main" in entrypoint
    assert 'Path(sys.argv[0]).stem == "docker-credential-rvs"' in shared_entrypoint
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
