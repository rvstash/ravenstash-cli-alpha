from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from pathlib import Path

from rvs import update as update_mod
from rvs.cli import app
from typer.testing import CliRunner


runner = CliRunner()


def _completed(returncode: int = 0, stdout: str = "") -> Any:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


def test_update_reports_new_apt_candidate(monkeypatch: Any) -> None:
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.2.2", "0.3.0"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)

    result = runner.invoke(app, ["update"])

    assert result.exit_code == 0
    assert "0.3.0 is available" in result.output
    assert "rvs update --apply" in result.output


def test_update_does_not_self_replace_non_apt_install(monkeypatch: Any) -> None:
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: (None, None))
    monkeypatch.setattr(update_mod, "_cli_version", lambda: "0.3.0")

    result = runner.invoke(app, ["update"])

    assert result.exit_code == 0
    assert "not managed by the rvs APT package" in result.output
    assert "install.sh" in result.output


def test_update_apply_uses_fixed_apt_paths(monkeypatch: Any) -> None:
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.2.2", "0.3.0"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod.os, "geteuid", lambda: 0)
    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> Any:
        calls.append(command)
        return _completed()

    monkeypatch.setattr(update_mod, "_run_visible", fake_run)

    result = runner.invoke(app, ["update", "--apply", "--yes"])

    assert result.exit_code == 0
    assert calls == [
        ["/usr/bin/apt-get", "update"],
        ["/usr/bin/apt-get", "install", "--only-upgrade", "--yes", "rvs"],
    ]


def test_update_rejects_candidate_outside_configured_channel(monkeypatch: Any) -> None:
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: ("0.3.1", "0.4.0"))
    monkeypatch.setattr(update_mod, "_upgrade_available", lambda installed, candidate: True)
    monkeypatch.setattr(update_mod, "_current_channel", lambda: "v0.3")

    result = runner.invoke(app, ["update"])

    assert result.exit_code == 1
    assert "does not belong to configured channel v0.3" in result.output


def test_upgrade_changes_channel_only_after_authenticated_manifest(
    monkeypatch: Any, tmp_path: Path
) -> None:
    versions = iter((("0.3.4", "0.3.4"), ("0.3.4", "0.4.0")))
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: next(versions))
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

    result = runner.invoke(app, ["upgrade", "--to", "0.4", "--yes"])

    assert result.exit_code == 0
    assert installed_sources == [update_mod._source_for_channel("v0.4")]
    assert calls == [
        ["/usr/bin/apt-get", "update"],
        ["/usr/bin/apt-get", "install", "--only-upgrade", "--yes", "rvs"],
    ]
    assert "compatibility channel v0.4" in result.output


def test_upgrade_restores_source_when_target_candidate_is_wrong(
    monkeypatch: Any, tmp_path: Path
) -> None:
    previous_source = update_mod._source_for_channel("v0.3")
    versions = iter((("0.3.4", "0.3.4"), ("0.3.4", "1.0.0")))
    monkeypatch.setattr(update_mod, "_apt_versions", lambda: next(versions))
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

    result = runner.invoke(app, ["upgrade", "--to", "0.4", "--yes"])

    assert result.exit_code == 1
    assert restored == [previous_source]
    assert "incompatible candidate" in result.output
