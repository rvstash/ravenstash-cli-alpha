from __future__ import annotations

import os
import shutil
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


def test_release_metadata_uses_apache_license() -> None:
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    notice_text = (ROOT / "NOTICE").read_text(encoding="utf-8")
    project_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "Apache License\n                           Version 2.0" in license_text
    assert "Copyright 2026 Ravenstash" in notice_text
    assert 'license = "Apache-2.0"' in project_text


def test_release_artifacts_include_license_and_notice() -> None:
    shell_builds = [
        (ROOT / "packaging/scripts/build-tarball.sh").read_text(encoding="utf-8"),
        (ROOT / "packaging/scripts/build-deb.sh").read_text(encoding="utf-8"),
    ]
    portable_build = (ROOT / "packaging/scripts/build_portable.py").read_text(encoding="utf-8")

    for build in shell_builds:
        assert "cp LICENSE" in build
        assert "cp NOTICE" in build
    assert 'ROOT / "LICENSE"' in portable_build
    assert 'ROOT / "NOTICE"' in portable_build


def test_portable_bundle_includes_runtime_dependency_license_metadata() -> None:
    spec = (ROOT / "packaging/pyinstaller/rvs.spec").read_text(encoding="utf-8")

    assert '"cryptography"' in spec
    assert '"httpcore2"' in spec
    assert '"httpx2"' in spec
    assert '"idna"' in spec
    assert '"truststore"' in spec
    assert '"httpcore"' not in spec
    assert '"httpx"' not in spec
    assert "datas += _metadata(distribution)" in spec


def test_runtime_sbom_does_not_emit_an_unknown_project_requirement() -> None:
    build = (ROOT / "packaging/scripts/build-release-artifacts.sh").read_text(encoding="utf-8")

    assert "--no-emit-project" in build


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


def test_release_keeps_target_handoffs_isolated() -> None:
    release_text = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    jobs = yaml.safe_load(release_text)["jobs"]
    build_jobs = {name: job for name, job in jobs.items() if "uses" in job}
    artifact_names = [
        Path(path).name
        for job in build_jobs.values()
        for path in job["with"]["artifact_paths"].splitlines()
    ]

    assert "merge-multiple: true" not in release_text
    assert "Download isolated target handoffs" in release_text
    assert 'test "${#matches[@]}" = 1' in release_text
    assert len(build_jobs) == 8
    assert {job["needs"] for job in build_jobs.values()} == {"validate"}
    assert len(artifact_names) == len(set(artifact_names)) == 10
    assert set(jobs["assemble"]["needs"]) == set(build_jobs)


def test_top_level_workflow_run_names_are_distinct_and_purpose_first() -> None:
    expected_prefixes = {
        "ci.yml": "${{ github.event_name == 'pull_request'",
        "platform-certification.yml": "${{ github.event_name == 'schedule'",
        "promote-installer.yml": "Promote rvs ",
        "refresh-apt.yml": "${{ github.event_name == 'schedule'",
        "release.yml": "${{ inputs.kind == 'candidate'",
        "test-build.yml": "Test build ·",
    }

    for filename, prefix in expected_prefixes.items():
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
        )
        assert workflow["run-name"].startswith(prefix)
        assert "github.sha" not in workflow["run-name"]
        assert "inputs.source_sha" not in workflow["run-name"]


def test_protected_branch_has_stable_aggregate_ci_gates() -> None:
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"]
    gate = jobs["gate"]
    assert gate["name"] == "CI gate"
    assert set(gate["needs"]) == {
        "changes",
        "quality",
        "platform-tests",
        "package-smoke",
        "release-policy",
        "nix",
    }
    assert jobs["quality"]["needs"] == "changes"
    assert jobs["platform-tests"]["needs"] == "changes"
    assert jobs["package-smoke"]["needs"] == "changes"
    assert jobs["release-policy"]["needs"] == "changes"
    assert jobs["nix"]["needs"] == "changes"


def test_publication_graph_parallelizes_safe_jobs_and_serializes_mutations() -> None:
    publication = yaml.safe_load(
        (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    )
    jobs = publication["jobs"]

    assert "needs" not in jobs["validate"]
    assert jobs["restore-apt"]["needs"] == "validate"
    assert set(jobs["sign"]["needs"]) == {"assemble", "restore-apt"}
    assert jobs["publish-apt"]["needs"] == "sign"
    assert jobs["verify-apt"]["needs"] == "publish-apt"
    assert jobs["verify-apt"]["strategy"]["fail-fast"] is False
    assert len(jobs["verify-apt"]["strategy"]["matrix"]["include"]) == 2
    assert set(jobs["publish-github-release"]["needs"]) == {"sign", "verify-apt"}
    assert jobs["restore-apt"]["if"] == "inputs.kind == 'stable'"
    assert jobs["publish-apt"]["if"] == "inputs.kind == 'stable'"
    assert jobs["verify-apt"]["if"] == "inputs.kind == 'stable'"


def test_release_builds_once_and_appends_architectures_once() -> None:
    publication = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    append = "packaging/repository/append_and_sign_apt.sh"

    assert "candidate_run_id" not in publication
    assert "release-candidate.yml" not in publication
    assert "refs/remotes/origin/${SOURCE_BRANCH}" in publication
    assert "inputs.kind == 'candidate'" in publication
    assert "--prerelease" in publication
    for gate in ("ci.yml", "platform-certification.yml"):
        assert gate in publication
    assert "platform-ci.yml" not in publication
    assert "release-policy-ci.yml" not in publication
    assert "rvs-release-${{ inputs.source_sha }}" in publication
    assert publication.count(append) == 1
    assert '"build/rvs_${VERSION}_amd64.deb"' in publication
    assert '"build/rvs_${VERSION}_arm64.deb"' in publication
    assert "RVS_APT_PROMOTE_CHANNEL" not in publication


def test_test_build_is_expiring_unsigned_and_never_publishes() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/test-build.yml").read_text(encoding="utf-8")
    )
    jobs = workflow["jobs"]
    build_jobs = {name: job for name, job in jobs.items() if "uses" in job}

    assert len(build_jobs) == 8
    assert {job["needs"] for job in build_jobs.values()} == {"prepare"}
    assert all(job["with"]["artifact_prefix"] == "rvs-test-target" for job in build_jobs.values())
    assert all("version_override" in job["with"] for job in build_jobs.values())
    assert jobs["assemble"]["steps"][-2]["with"]["retention-days"] == 7
    workflow_text = (ROOT / ".github/workflows/test-build.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in workflow_text
    assert "contents: write" not in workflow_text
    assert "gh release" not in workflow_text
    assert "publish_apt" not in workflow_text
    assert "cosign" not in workflow_text


def test_successful_publication_is_not_failed_by_best_effort_cleanup() -> None:
    publication = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    promotion = (ROOT / ".github/workflows/promote-installer.yml").read_text(encoding="utf-8")

    assert "Delete current-run handoffs\n        continue-on-error: true" in publication
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


@pytest.mark.skipif(os.name == "nt", reason="release-slot tooling is POSIX-only")
def test_release_slot_check_accepts_candidate_tag(tmp_path: Path) -> None:
    binary = tmp_path / "bin"
    binary.mkdir()
    gh = binary / "gh"
    gh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    gh.chmod(0o755)

    result = subprocess.run(
        [
            str(ROOT / "packaging/scripts/assert-github-release-slot-empty.sh"),
            "rvstash/ravenstash-cli-alpha",
            "v0.13.5rc1",
        ],
        check=False,
        env=os.environ | {"PATH": f"{binary}{os.pathsep}{os.environ['PATH']}"},
    )

    assert result.returncode == 0


def test_ci_only_tracks_canonical_release_branches() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert workflow.count('branches: [main, "release/v*.*"]') == 2
    assert 'branches: [main, "release/**"]' not in workflow


def test_reusable_builder_uses_exact_bundles_and_supplies_musl_bash() -> None:
    builder = (ROOT / ".github/workflows/_build-release-target.yml").read_text(encoding="utf-8")

    assert "apk add --no-cache bash binutils build-base libffi-dev" in builder
    assert 'bundle="build/release/rvs-v${VERSION}-${TARGET}"' in builder
    assert "find build/release" not in builder
    assert builder.count('test -d "$bundle"') == 2
    assert "prepare_test_build.py apply" in builder


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


@pytest.mark.skipif(shutil.which("dpkg") is None, reason="dpkg is unavailable")
def test_release_candidate_uses_debian_prerelease_ordering() -> None:
    helper = ROOT / "packaging/scripts/common.sh"
    converted = subprocess.run(
        ["bash", "-c", f'source "{helper}"; rvs_debian_version 0.14.0rc2'],
        check=True,
        capture_output=True,
        text=True,
    )
    ordering = subprocess.run(
        ["dpkg", "--compare-versions", converted.stdout.strip(), "lt", "0.14.0"],
        check=False,
    )

    assert converted.stdout == "0.14.0~rc2\n"
    assert ordering.returncode == 0


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
    channel = f"v{major}.{minor}"

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
        locale = package.extractfile(
            "package-manifests/winget/Ravenstash.rvs.v0.12.locale.en-US.yaml"
        )
        assert locale is not None
        locale_text = locale.read().decode()
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
    assert "License: Apache-2.0" in locale_text
    assert "ravenstash-cli-alpha/releases/download/v0.12.0" in installer_text
    assert 'arch arm: "arm64", intel: "amd64"' in cask_text
