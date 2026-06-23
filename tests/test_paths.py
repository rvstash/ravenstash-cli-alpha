from __future__ import annotations

from rvn import paths


def test_rvn_home_defaults_to_home_rvn(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("RVN_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert paths.rvn_home() == tmp_path / ".rvn"


def test_rvn_home_uses_environment_override(monkeypatch, tmp_path) -> None:
    configured = tmp_path / "custom-rvn"
    monkeypatch.setenv("RVN_HOME", str(configured))

    assert paths.rvn_home() == configured
    assert paths.rvn_path("runtimes", "python") == configured / "runtimes" / "python"
