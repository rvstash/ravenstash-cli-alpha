from __future__ import annotations

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
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool) -> Any:
        assert check is False
        calls.append(command)
        return _completed()

    monkeypatch.setattr(update_mod.subprocess, "run", fake_run)

    result = runner.invoke(app, ["update", "--apply", "--yes"])

    assert result.exit_code == 0
    assert calls == [
        ["/usr/bin/apt-get", "update"],
        ["/usr/bin/apt-get", "install", "--only-upgrade", "--yes", "rvs"],
    ]
