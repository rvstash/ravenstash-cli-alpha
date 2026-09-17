from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from rvs import portable_update as portable_update_mod
from rvs import update as update_mod
from rvs.cli import app
from rvs.installations import Installation
from typer.testing import CliRunner


runner = CliRunner()


def _completed(returncode: int = 0, stdout: str = "") -> Any:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


def test_update_reports_new_apt_candidate(monkeypatch: Any) -> None:
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.14.3", "0.14.4"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0")

    result = runner.invoke(app, ["update"])

    assert result.exit_code == 0
    assert "0.14.4 is available" in result.output
    assert "rvs update --apply" in result.output


def test_update_reports_installed_and_latest_versions_when_current(monkeypatch: Any) -> None:
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.14.3", "0.14.3"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: False)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0")
    monkeypatch.setattr(update_mod, "_announce_new_channel", lambda channel: None)

    result = runner.invoke(app, ["update"])
    output = " ".join(result.output.split())

    assert result.exit_code == 0
    assert "Installed: rvs 0.14.3" in output
    assert "Latest in release channel v0: rvs 0.14.3" in output
    assert "You are up to date" in output


def test_update_does_not_self_replace_unmanaged_install(monkeypatch: Any) -> None:
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: (None, None))
    monkeypatch.setattr(update_mod, "_cli_version", lambda: "0.14.4")

    result = runner.invoke(app, ["update"])

    assert result.exit_code == 0
    assert "not a recognized managed installation" in result.output
    assert "install.sh" in result.output


def test_nix_detection_excludes_source_test_environment() -> None:
    assert not update_mod._is_nix_application_executable(
        "/nix/store/abc123-ravenstash-cli-test-env/bin/python3"
    )


def test_nix_detection_recognizes_packaged_application_environment() -> None:
    assert update_mod._is_nix_application_executable(
        "/nix/store/abc123-ravenstash-cli-env/bin/python3"
    )


def _portable(tmp_path: Path) -> Installation:
    return Installation(
        1,
        "portable",
        "user",
        "0.14.3",
        "v0",
        "linux-musl-amd64",
        str(tmp_path / "root"),
        str(tmp_path / "bin"),
    )


def test_portable_update_previews_signed_channel_release(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: (None, None))
    monkeypatch.setattr(update_mod, "_portable_installation", lambda: _portable(tmp_path))
    monkeypatch.setattr(
        update_mod,
        "fetch_channel_manifest",
        lambda: {
            "schema": 1,
            "recommended": "v0",
            "channels": {
                "v0": {
                    "latest": "0.14.4",
                    "minor_targets": {"0.14": "0.14.4"},
                    "status": "supported",
                }
            },
        },
    )

    result = runner.invoke(app, ["update"])

    assert result.exit_code == 0, result.output
    assert "0.14.4 is available for linux-musl-amd64" in result.output
    assert "rvs update --apply" in result.output


def test_portable_update_applies_exact_candidate(monkeypatch: Any, tmp_path: Path) -> None:
    calls: list[tuple[Installation, str, bool]] = []
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: (None, None))
    monkeypatch.setattr(update_mod, "_portable_installation", lambda: _portable(tmp_path))
    monkeypatch.setattr(
        update_mod,
        "apply_portable_update",
        lambda installation, version, *, candidate: (
            calls.append((installation, version, candidate)) or False
        ),
    )

    result = runner.invoke(app, ["update", "--candidate", "0.14.4rc1", "--apply", "--yes"])

    assert result.exit_code == 0, result.output
    assert calls == [(_portable(tmp_path), "0.14.4rc1", True)]
    assert "Updated rvs to 0.14.4rc1" in result.output


def test_winget_update_uses_exact_series_identifier(monkeypatch: Any) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: (None, None))
    monkeypatch.setattr(update_mod, "_portable_installation", lambda: None)
    monkeypatch.setattr(update_mod, "_managed_method", lambda: "winget")
    monkeypatch.setattr(update_mod, "_cli_version", lambda: "0.14.3")
    monkeypatch.setattr(update_mod.shutil, "which", lambda command: command)
    monkeypatch.setattr(
        update_mod,
        "fetch_channel_manifest",
        lambda: {
            "schema": 1,
            "recommended": "v0",
            "channels": {
                "v0": {
                    "latest": "0.14.4",
                    "minor_targets": {"0.14": "0.14.4"},
                    "status": "supported",
                }
            },
        },
    )
    monkeypatch.setattr(
        update_mod.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command) or _completed(),
    )

    result = runner.invoke(app, ["update", "--apply", "--yes"])

    assert result.exit_code == 0, result.output
    assert calls == [["winget", "upgrade", "--exact", "--id", "Ravenstash.rvs.v0"]]


def test_nix_update_replaces_pinned_tag_and_rolls_back_on_failure(monkeypatch: Any) -> None:
    calls: list[list[str]] = []
    return_codes = iter((0, 1, 0))
    monkeypatch.setattr(update_mod.shutil, "which", lambda command: command)
    monkeypatch.setattr(
        update_mod.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command) or _completed(next(return_codes)),
    )

    try:
        update_mod._replace_nix_profile("0.14.3", "0.14.4")
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("failed Nix replacement did not exit")

    repository = "github:rvstash/ravenstash-cli-alpha"
    assert calls == [
        ["nix", "profile", "remove", "ravenstash-cli"],
        ["nix", "profile", "install", f"{repository}/v0.14.4"],
        ["nix", "profile", "install", f"{repository}/v0.14.3"],
    ]


def test_homebrew_exact_minor_selector_fails_without_mutating_package_state(
    monkeypatch: Any,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: (None, None))
    monkeypatch.setattr(update_mod, "_portable_installation", lambda: None)
    monkeypatch.setattr(update_mod, "_managed_method", lambda: "homebrew")
    monkeypatch.setattr(update_mod, "_cli_version", lambda: "0.14.3")
    monkeypatch.setattr(update_mod.shutil, "which", lambda command: command)
    monkeypatch.setattr(
        update_mod,
        "fetch_channel_manifest",
        lambda: {
            "schema": 1,
            "recommended": "v0",
            "channels": {
                "v0": {
                    "latest": "0.16.0",
                    "minor_targets": {"0.15": "0.15.2", "0.16": "0.16.0"},
                    "status": "supported",
                }
            },
        },
    )
    monkeypatch.setattr(
        update_mod.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command) or _completed(),
    )

    result = runner.invoke(app, ["update", "--to", "0.15", "--apply", "--yes"])

    assert result.exit_code == 1
    assert "signed portable installer" in result.output
    assert calls == []


def test_candidate_version_maps_to_debian_prerelease() -> None:
    assert update_mod._candidate_debian_version("0.14.4rc2") == "0.14.4~rc2"


def test_candidate_preview_verifies_without_installing(monkeypatch: Any, tmp_path: Path) -> None:
    (tmp_path / "dpkg-deb").touch()
    monkeypatch.setattr(update_mod, "_DPKG_DEB", tmp_path / "dpkg-deb")
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.14.3", "0.14.3"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)

    def fake_download(candidate: str, destination: Path) -> Path:
        package = destination / f"rvs_{candidate}_amd64.deb"
        package.touch()
        return package

    monkeypatch.setattr(update_mod, "_download_candidate", fake_download)
    monkeypatch.setattr(
        update_mod,
        "_run_visible",
        lambda command: (_ for _ in ()).throw(AssertionError("preview installed a package")),
    )

    result = runner.invoke(app, ["update", "--candidate", "0.14.4rc1"])

    assert result.exit_code == 0, result.output
    assert "Verified signed release candidate rvs 0.14.4rc1" in result.output
    assert "--candidate 0.14.4rc1 --apply" in result.output


def test_candidate_apply_installs_verified_local_package(monkeypatch: Any, tmp_path: Path) -> None:
    apt_get = tmp_path / "apt-get"
    dpkg_deb = tmp_path / "dpkg-deb"
    for path in (apt_get, dpkg_deb):
        path.touch()
    monkeypatch.setattr(update_mod, "_APT_GET", apt_get)
    monkeypatch.setattr(update_mod, "_DPKG_DEB", dpkg_deb)
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.14.3", "0.14.3"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)

    def fake_download(candidate: str, destination: Path) -> Path:
        package = destination / f"rvs_{candidate}_amd64.deb"
        package.touch()
        return package

    monkeypatch.setattr(update_mod, "_download_candidate", fake_download)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        update_mod,
        "_run_visible",
        lambda command: calls.append(command) or _completed(),
    )

    result = runner.invoke(app, ["update", "--candidate", "0.14.4rc1", "--apply", "--yes"])

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0][:3] == [str(apt_get), "install", "--yes"]
    assert Path(calls[0][3]).name == "rvs_0.14.4rc1_amd64.deb"


def test_candidate_rejects_stable_version_and_series_option(monkeypatch: Any) -> None:
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: (None, None))
    invalid = runner.invoke(app, ["update", "--candidate", "0.14.3"])
    combined = runner.invoke(app, ["update", "--candidate", "0.14.4rc1", "--to", "0.14"])

    assert invalid.exit_code == 1
    assert "must look like 0.14.4rc1" in invalid.output
    assert combined.exit_code == 1
    assert "cannot be used together" in combined.output


def test_candidate_download_authenticates_release_assets(monkeypatch: Any, tmp_path: Path) -> None:
    candidate = "0.14.4rc1"
    package_name = f"rvs_{candidate}_amd64.deb"
    package = b"signed candidate package"
    checksum_name = f"rvs-v{candidate}-checksums.txt"
    checksum = f"{hashlib.sha256(package).hexdigest()}  {package_name}\n".encode()
    signature_name = f"{checksum_name}.asc"
    tag = f"v{candidate}"
    root = f"{portable_update_mod.RELEASE_DOWNLOAD_ROOT}/{tag}"
    payloads = {
        f"{root}/{package_name}": package,
        f"{root}/{checksum_name}": checksum,
        f"{root}/{signature_name}": b"signature",
    }
    release = {
        "tag_name": tag,
        "draft": False,
        "prerelease": True,
        "assets": [
            {"name": name, "browser_download_url": f"{root}/{name}"}
            for name in (package_name, checksum_name, signature_name)
        ],
    }

    class Response:
        def __init__(self, content: bytes = b"", json_data: Any = None) -> None:
            self.content = content
            self._json = json_data

        def raise_for_status(self) -> None:
            return None

        def json(self) -> Any:
            return self._json

    class Client:
        def __enter__(self) -> Client:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def get(self, url: str, **_kwargs: Any) -> Response:
            if url == f"{portable_update_mod.RELEASE_API}/releases/tags/{tag}":
                return Response(json_data=release)
            return Response(content=payloads[url])

    monkeypatch.setattr(portable_update_mod.httpx, "Client", lambda **_kwargs: Client())
    monkeypatch.setattr(portable_update_mod, "verify_detached", lambda *_args: None)
    monkeypatch.setattr(update_mod.platform, "machine", lambda: "x86_64")

    metadata_commands: list[list[str]] = []

    def fake_run(command: list[str]) -> Any:
        metadata_commands.append(command)
        return _completed(stdout="rvs\n0.14.4~rc1\namd64\n")

    monkeypatch.setattr(update_mod, "_run", fake_run)

    result = update_mod._download_candidate(candidate, tmp_path)

    assert result == tmp_path / package_name
    assert result.read_bytes() == package
    assert metadata_commands == [
        [
            str(update_mod._DPKG_DEB),
            "--show",
            "--showformat=${Package}\\n${Version}\\n${Architecture}\\n",
            str(result),
        ]
    ]


def test_apt_source_recognizes_rolling_v0_on_arm64() -> None:
    source = (
        "deb [arch=arm64 signed-by=/etc/apt/keyrings/ravenstash-rvs.gpg] "
        "https://releases.ravenstash.com/rvs/apt v0 main"
    )

    assert update_mod._SOURCE_PATTERN.fullmatch(source)


def test_update_apply_uses_fixed_apt_paths(monkeypatch: Any, tmp_path: Path) -> None:
    assert update_mod._APT_GET == Path("/usr/bin/apt-get")
    apt_get = tmp_path / "apt-get"
    apt_get.touch()
    monkeypatch.setattr(update_mod, "_APT_GET", apt_get)
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.14.3", "0.14.4"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0")
    monkeypatch.setattr(update_mod.os, "geteuid", lambda: 0, raising=False)
    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> Any:
        calls.append(command)
        return _completed()

    monkeypatch.setattr(update_mod, "_run_visible", fake_run)

    result = runner.invoke(app, ["update", "--apply", "--yes"])

    assert result.exit_code == 0
    assert calls == [
        [str(apt_get), "update"],
        [str(apt_get), "install", "--only-upgrade", "--yes", "rvs=0.14.4"],
    ]


def test_update_rejects_candidate_outside_configured_channel(monkeypatch: Any) -> None:
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.14.3", "1.0.0"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0")

    result = runner.invoke(app, ["update"])

    assert result.exit_code == 1
    assert "does not belong to configured release channel v0" in result.output


def test_exact_minor_upgrade_uses_authenticated_manifest_without_changing_source(
    monkeypatch: Any,
) -> None:
    versions = iter((("0.14.3", "0.16.0"), ("0.14.3", "0.16.0")))
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: next(versions))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0")
    monkeypatch.setattr(
        update_mod,
        "_channel_manifest",
        lambda: {
            "schema": 1,
            "recommended": "v0",
            "channels": {
                "v0": {
                    "latest": "0.16.0",
                    "minor_targets": {"0.14": "0.14.3", "0.15": "0.15.2"},
                    "status": "supported",
                },
            },
        },
    )
    calls: list[list[str]] = []

    def fake_visible(command: list[str]) -> Any:
        calls.append(command)
        return _completed()

    monkeypatch.setattr(update_mod, "_run_visible", fake_visible)

    result = runner.invoke(app, ["update", "--apply", "--to", "0.15", "--yes"])

    assert result.exit_code == 0
    assert calls == [
        [str(update_mod._APT_GET), "update"],
        [str(update_mod._APT_GET), "install", "--only-upgrade", "--yes", "rvs=0.15.2"],
    ]
    assert "minor release 0.15" in result.output


def test_exact_minor_rejects_unpublished_target_without_apt_changes(monkeypatch: Any) -> None:
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.14.3", "0.16.0"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0")
    monkeypatch.setattr(
        update_mod,
        "_channel_manifest",
        lambda: {
            "schema": 1,
            "recommended": "v0",
            "channels": {
                "v0": {
                    "latest": "0.16.0",
                    "minor_targets": {"0.16": "0.16.0"},
                    "status": "supported",
                }
            },
        },
    )
    monkeypatch.setattr(
        update_mod,
        "_run_visible",
        lambda command: (_ for _ in ()).throw(AssertionError("APT was changed")),
    )

    result = runner.invoke(app, ["update", "--apply", "--to", "0.15", "--yes"])

    assert result.exit_code == 1
    assert "minor release 0.15 is not available" in result.output


def test_update_to_only_previews_and_never_changes_apt_source(monkeypatch):
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.14.3", "0.14.3"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0")
    monkeypatch.setattr(
        update_mod,
        "_channel_manifest",
        lambda: {
            "schema": 1,
            "recommended": "v0",
            "channels": {
                "v0": {
                    "latest": "0.16.0",
                    "minor_targets": {"0.15": "0.15.2", "0.16": "0.16.0"},
                    "status": "supported",
                }
            },
        },
    )

    def unexpected(*_args, **_kwargs):
        raise AssertionError("preview attempted an APT change")

    monkeypatch.setattr(update_mod, "_run_visible", unexpected)
    monkeypatch.setattr(update_mod.typer, "confirm", unexpected)
    result = runner.invoke(app, ["update", "--to", "0.15"])
    assert result.exit_code == 0, result.output
    assert "0.15.2" in result.stdout
    assert "--apply" in result.stdout


def test_update_yes_requires_explicit_apply(monkeypatch):
    monkeypatch.setattr(
        update_mod,
        "_apt_versions",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected APT read")),
    )
    result = runner.invoke(app, ["update", "--to", "0.15", "--yes"])
    assert result.exit_code == 1
    assert "--yes requires --apply" in result.stderr


def test_update_to_current_series_still_applies_available_update(monkeypatch, tmp_path):
    apt_get = tmp_path / "apt-get"
    apt_get.touch()
    monkeypatch.setattr(update_mod, "_APT_GET", apt_get)
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.15.0", "0.15.1"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0")
    monkeypatch.setattr(
        update_mod,
        "_channel_manifest",
        lambda: {
            "channels": {
                "v0": {
                    "latest": "0.16.0",
                    "minor_targets": {"0.15": "0.15.1", "0.16": "0.16.0"},
                    "status": "supported",
                }
            }
        },
    )
    calls = []
    monkeypatch.setattr(
        update_mod, "_run_visible", lambda command: calls.append(command) or _completed()
    )
    result = runner.invoke(app, ["update", "--to", "0.15", "--apply", "--yes"])
    assert result.exit_code == 0, result.output
    assert calls[-1] == [str(apt_get), "install", "--only-upgrade", "--yes", "rvs=0.15.1"]


def test_update_to_rejects_package_downgrade_before_source_change(monkeypatch):
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.16.0", "0.14.3"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: False)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0")
    monkeypatch.setattr(
        update_mod,
        "_channel_manifest",
        lambda: {
            "channels": {
                "v0": {
                    "latest": "0.16.0",
                    "minor_targets": {"0.15": "0.15.0"},
                    "status": "supported",
                }
            }
        },
    )
    result = runner.invoke(app, ["update", "--to", "0.15", "--apply", "--yes"])
    assert result.exit_code == 1
    assert "not newer" in result.stderr


def test_update_to_stops_if_installed_package_changes(monkeypatch):
    versions = iter((("0.14.3", "0.14.3"), ("0.16.0", "0.15.0")))
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: next(versions))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0")
    monkeypatch.setattr(
        update_mod,
        "_channel_manifest",
        lambda: {
            "channels": {
                "v0": {
                    "latest": "0.16.0",
                    "minor_targets": {"0.15": "0.15.0"},
                    "status": "supported",
                }
            }
        },
    )
    calls = []
    monkeypatch.setattr(
        update_mod, "_run_visible", lambda command: calls.append(command) or _completed()
    )
    result = runner.invoke(app, ["update", "--to", "0.15", "--apply", "--yes"])
    assert result.exit_code == 1
    assert calls == [[str(update_mod._APT_GET), "update"]]
