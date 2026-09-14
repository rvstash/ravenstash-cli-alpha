from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from rvs import update as update_mod
from rvs.cli import app
from typer.testing import CliRunner


runner = CliRunner()


def _completed(returncode: int = 0, stdout: str = "") -> Any:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


def test_update_reports_new_apt_candidate(monkeypatch: Any) -> None:
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.2.2", "0.3.0"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0.3")

    result = runner.invoke(app, ["update"])

    assert result.exit_code == 0
    assert "0.3.0 is available" in result.output
    assert "rvs update --apply" in result.output


def test_update_reports_installed_and_latest_versions_when_current(monkeypatch: Any) -> None:
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.13.2", "0.13.2"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: False)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0.13")
    monkeypatch.setattr(update_mod, "_announce_new_channel", lambda channel: None)

    result = runner.invoke(app, ["update"])
    output = " ".join(result.output.split())

    assert result.exit_code == 0
    assert "Installed: rvs 0.13.2" in output
    assert "Latest in release series v0.13: rvs 0.13.2" in output
    assert "You are up to date" in output


def test_update_does_not_self_replace_non_apt_install(monkeypatch: Any) -> None:
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: (None, None))
    monkeypatch.setattr(update_mod, "_cli_version", lambda: "0.3.0")

    result = runner.invoke(app, ["update"])

    assert result.exit_code == 0
    assert "not managed by the rvs APT package" in result.output
    assert "install.sh" in result.output


def test_candidate_version_maps_to_debian_prerelease() -> None:
    assert update_mod._candidate_debian_version("0.14.0rc2") == "0.14.0~rc2"


def test_candidate_preview_verifies_without_installing(monkeypatch: Any, tmp_path: Path) -> None:
    for name in ("gpgv", "dpkg-deb"):
        (tmp_path / name).touch()
    monkeypatch.setattr(update_mod, "_APT_KEYRING", tmp_path / "keyring")
    update_mod._APT_KEYRING.touch()
    monkeypatch.setattr(update_mod, "_GPGV", tmp_path / "gpgv")
    monkeypatch.setattr(update_mod, "_DPKG_DEB", tmp_path / "dpkg-deb")
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.13.4", "0.13.4"))
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

    result = runner.invoke(app, ["update", "--candidate", "0.14.0rc1"])

    assert result.exit_code == 0, result.output
    assert "Verified signed release candidate rvs 0.14.0rc1" in result.output
    assert "--candidate 0.14.0rc1 --apply" in result.output


def test_candidate_apply_installs_verified_local_package(monkeypatch: Any, tmp_path: Path) -> None:
    apt_get = tmp_path / "apt-get"
    gpgv = tmp_path / "gpgv"
    dpkg_deb = tmp_path / "dpkg-deb"
    keyring = tmp_path / "keyring"
    for path in (apt_get, gpgv, dpkg_deb, keyring):
        path.touch()
    monkeypatch.setattr(update_mod, "_APT_GET", apt_get)
    monkeypatch.setattr(update_mod, "_APT_KEYRING", keyring)
    monkeypatch.setattr(update_mod, "_GPGV", gpgv)
    monkeypatch.setattr(update_mod, "_DPKG_DEB", dpkg_deb)
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.13.4", "0.13.4"))
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

    result = runner.invoke(app, ["update", "--candidate", "0.14.0rc1", "--apply", "--yes"])

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0][:3] == [str(apt_get), "install", "--yes"]
    assert Path(calls[0][3]).name == "rvs_0.14.0rc1_amd64.deb"


def test_candidate_rejects_stable_version_and_series_option(monkeypatch: Any) -> None:
    invalid = runner.invoke(app, ["update", "--candidate", "0.14.0"])
    combined = runner.invoke(app, ["update", "--candidate", "0.14.0rc1", "--to", "0.14"])

    assert invalid.exit_code == 1
    assert "must look like 0.14.0rc1" in invalid.output
    assert combined.exit_code == 1
    assert "cannot be used together" in combined.output


def test_candidate_download_authenticates_release_assets(monkeypatch: Any, tmp_path: Path) -> None:
    candidate = "0.14.0rc1"
    package_name = f"rvs_{candidate}_amd64.deb"
    package = b"signed candidate package"
    checksum_name = f"rvs-v{candidate}-checksums.txt"
    checksum = f"{hashlib.sha256(package).hexdigest()}  {package_name}\n".encode()
    signature_name = f"{checksum_name}.asc"
    tag = f"v{candidate}"
    root = f"{update_mod._RELEASE_DOWNLOAD_ROOT}/{tag}"
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
            if url == f"{update_mod._GITHUB_API}/releases/tags/{tag}":
                return Response(json_data=release)
            return Response(content=payloads[url])

    monkeypatch.setattr(update_mod.httpx, "Client", lambda **_kwargs: Client())
    monkeypatch.setattr(update_mod.platform, "machine", lambda: "x86_64")

    def fake_run(command: list[str]) -> Any:
        if command[0] == str(update_mod._GPGV):
            return _completed()
        return _completed(stdout="rvs\n0.14.0~rc1\namd64\n")

    monkeypatch.setattr(update_mod, "_run", fake_run)

    result = update_mod._download_candidate(candidate, tmp_path)

    assert result == tmp_path / package_name
    assert result.read_bytes() == package


def test_apt_source_uses_native_arm64_architecture(monkeypatch: Any) -> None:
    monkeypatch.setattr(update_mod.platform, "machine", lambda: "aarch64")

    source = update_mod._source_for_channel("v0.12")

    assert "arch=arm64" in source
    assert update_mod._SOURCE_PATTERN.fullmatch(source.strip())


def test_update_apply_uses_fixed_apt_paths(monkeypatch: Any, tmp_path: Path) -> None:
    assert update_mod._APT_GET == Path("/usr/bin/apt-get")
    apt_get = tmp_path / "apt-get"
    apt_get.touch()
    monkeypatch.setattr(update_mod, "_APT_GET", apt_get)
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.2.2", "0.3.0"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0.3")
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
        [str(apt_get), "install", "--only-upgrade", "--yes", "rvs=0.3.0"],
    ]


def test_update_rejects_candidate_outside_configured_channel(monkeypatch: Any) -> None:
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.3.1", "0.4.0"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0.3")

    result = runner.invoke(app, ["update"])

    assert result.exit_code == 1
    assert "does not belong to configured release series v0.3" in result.output


def test_upgrade_changes_channel_only_after_authenticated_manifest(
    monkeypatch: Any, tmp_path: Path
) -> None:
    versions = iter((("0.3.4", "0.3.4"), ("0.3.4", "0.4.0")))
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: next(versions))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0.3")
    monkeypatch.setattr(
        update_mod,
        "_channel_manifest",
        lambda: {
            "schema": 1,
            "recommended": "v0.4",
            "channels": {
                "v0.3": {"latest": "0.3.4", "status": "supported"},
                "v0.4": {
                    "latest": "0.4.0",
                    "status": "supported",
                    "migration_notes": "https://docs.ravenstash.com/cli/releases/0-4/",
                },
            },
        },
    )
    source_path = tmp_path / "ravenstash-rvs.list"
    source_path.write_text(update_mod._source_for_channel("v0.3"), encoding="utf-8")
    monkeypatch.setattr(update_mod, "_APT_SOURCE", source_path)
    installed_sources: list[str] = []
    monkeypatch.setattr(
        update_mod,
        "_install_source",
        lambda source: installed_sources.append(source) is None or True,
    )
    calls: list[list[str]] = []

    def fake_visible(command: list[str]) -> Any:
        calls.append(command)
        return _completed()

    monkeypatch.setattr(update_mod, "_run_visible", fake_visible)

    result = runner.invoke(app, ["update", "--apply", "--to", "0.4", "--yes"])

    assert result.exit_code == 0
    assert installed_sources == [update_mod._source_for_channel("v0.4")]
    assert calls == [
        [str(update_mod._APT_GET), "update"],
        [str(update_mod._APT_GET), "install", "--only-upgrade", "--yes", "rvs=0.4.0"],
    ]
    assert "release series v0.4" in result.output


def test_upgrade_restores_source_when_target_candidate_is_wrong(
    monkeypatch: Any, tmp_path: Path
) -> None:
    previous_source = update_mod._source_for_channel("v0.3")
    versions = iter((("0.3.4", "0.3.4"), ("0.3.4", "1.0.0")))
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: next(versions))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0.3")
    monkeypatch.setattr(
        update_mod,
        "_channel_manifest",
        lambda: {
            "schema": 1,
            "recommended": "v0.4",
            "channels": {"v0.4": {"latest": "0.4.0", "status": "supported"}},
        },
    )
    source_path = tmp_path / "ravenstash-rvs.list"
    source_path.write_text(previous_source, encoding="utf-8")
    monkeypatch.setattr(update_mod, "_APT_SOURCE", source_path)
    monkeypatch.setattr(update_mod, "_install_source", lambda source: True)
    restored: list[str] = []
    monkeypatch.setattr(update_mod, "_restore_source", restored.append)
    monkeypatch.setattr(update_mod, "_run_visible", lambda command: _completed())

    result = runner.invoke(app, ["update", "--apply", "--to", "0.4", "--yes"])

    assert result.exit_code == 1
    assert restored == [previous_source]
    assert "incompatible candidate" in result.output


def test_update_to_only_previews_and_never_changes_apt_source(monkeypatch):
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.3.4", "0.3.4"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0.3")
    monkeypatch.setattr(
        update_mod,
        "_channel_manifest",
        lambda: {
            "schema": 1,
            "recommended": "v0.4",
            "channels": {"v0.4": {"latest": "0.4.0", "status": "supported"}},
        },
    )

    def unexpected(*_args, **_kwargs):
        raise AssertionError("preview attempted an APT change")

    monkeypatch.setattr(update_mod, "_install_source", unexpected)
    monkeypatch.setattr(update_mod, "_run_visible", unexpected)
    monkeypatch.setattr(update_mod.typer, "confirm", unexpected)
    result = runner.invoke(app, ["update", "--to", "0.4"])
    assert result.exit_code == 0, result.output
    assert "0.4.0" in result.stdout
    assert "--apply" in result.stdout
    assert "breaking changes" in result.stderr


def test_update_yes_requires_explicit_apply(monkeypatch):
    monkeypatch.setattr(
        update_mod,
        "_apt_versions",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected APT read")),
    )
    result = runner.invoke(app, ["update", "--to", "0.4", "--yes"])
    assert result.exit_code == 1
    assert "--yes requires --apply" in result.stderr


def test_update_to_current_series_still_applies_available_update(monkeypatch, tmp_path):
    apt_get = tmp_path / "apt-get"
    apt_get.touch()
    monkeypatch.setattr(update_mod, "_APT_GET", apt_get)
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.4.0", "0.4.1"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0.4")
    calls = []
    monkeypatch.setattr(
        update_mod, "_run_visible", lambda command: calls.append(command) or _completed()
    )
    result = runner.invoke(app, ["update", "--to", "0.4", "--apply", "--yes"])
    assert result.exit_code == 0, result.output
    assert calls[-1] == [str(apt_get), "install", "--only-upgrade", "--yes", "rvs=0.4.1"]


def test_update_to_rejects_package_downgrade_before_source_change(monkeypatch):
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.5.0", "0.3.4"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: False)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0.3")
    monkeypatch.setattr(
        update_mod,
        "_channel_manifest",
        lambda: {"channels": {"v0.4": {"latest": "0.4.0", "status": "supported"}}},
    )
    changed = []
    monkeypatch.setattr(update_mod, "_install_source", changed.append)
    result = runner.invoke(app, ["update", "--to", "0.4", "--apply", "--yes"])
    assert result.exit_code == 1
    assert "not newer" in result.stderr
    assert changed == []


def test_update_to_restores_source_if_installed_package_changes(monkeypatch, tmp_path):
    versions = iter((("0.3.4", "0.3.4"), ("0.5.0", "0.4.0")))
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: next(versions))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0.3")
    monkeypatch.setattr(
        update_mod,
        "_channel_manifest",
        lambda: {"channels": {"v0.4": {"latest": "0.4.0", "status": "supported"}}},
    )
    source = tmp_path / "source.list"
    source.write_text("previous source\n")
    monkeypatch.setattr(update_mod, "_APT_SOURCE", source)
    monkeypatch.setattr(update_mod, "_install_source", lambda _: True)
    restored, calls = [], []
    monkeypatch.setattr(update_mod, "_restore_source", restored.append)
    monkeypatch.setattr(
        update_mod, "_run_visible", lambda command: calls.append(command) or _completed()
    )
    result = runner.invoke(app, ["update", "--to", "0.4", "--apply", "--yes"])
    assert result.exit_code == 1
    assert restored == ["previous source\n"]
    assert calls == [[str(update_mod._APT_GET), "update"]]
