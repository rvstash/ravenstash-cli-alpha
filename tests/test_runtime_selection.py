from __future__ import annotations

from typing import TYPE_CHECKING

from rvn.runtime import java as java_rt
from rvn.runtime import node as node_rt
from rvn.runtime import python as python_rt
from rvn.runtime import tools
from rvn.runtime.selection import selected_version


if TYPE_CHECKING:
    from pathlib import Path


def test_python_find_without_version_returns_latest_install(monkeypatch, tmp_path: Path) -> None:
    runtimes_dir = tmp_path / "runtimes"
    monkeypatch.setattr(python_rt, "RUNTIMES_DIR", runtimes_dir)
    (runtimes_dir / "python" / "3.11.9").mkdir(parents=True)
    (runtimes_dir / "python" / "3.12.3").mkdir()

    assert python_rt.find("") == runtimes_dir / "python" / "3.12.3"


def test_node_find_without_version_returns_latest_install(monkeypatch, tmp_path: Path) -> None:
    runtimes_dir = tmp_path / "runtimes"
    monkeypatch.setattr(node_rt, "RUNTIMES_DIR", runtimes_dir)
    (runtimes_dir / "node" / "22.11.0").mkdir(parents=True)
    (runtimes_dir / "node" / "24.14.1").mkdir()

    assert node_rt.find("") == runtimes_dir / "node" / "24.14.1"


def test_java_find_matches_major_and_without_version_returns_latest(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtimes_dir = tmp_path / "runtimes"
    monkeypatch.setattr(java_rt, "RUNTIMES_DIR", runtimes_dir)
    (runtimes_dir / "java" / "17.0.10+7").mkdir(parents=True)
    (runtimes_dir / "java" / "21.0.3+9").mkdir()

    assert java_rt.find("21") == runtimes_dir / "java" / "21.0.3+9"
    assert java_rt.find("") == runtimes_dir / "java" / "21.0.3+9"


def test_tools_resolve_prefers_project_pinned_python(monkeypatch, tmp_path: Path) -> None:
    runtimes_dir = tmp_path / "runtimes"
    py311_bin = runtimes_dir / "python" / "3.11.9" / "bin"
    py312_bin = runtimes_dir / "python" / "3.12.3" / "bin"
    py311_bin.mkdir(parents=True)
    py312_bin.mkdir(parents=True)
    (py311_bin / "pip").write_text("", encoding="utf-8")
    (py312_bin / "pip").write_text("", encoding="utf-8")
    (tmp_path / ".python-version").write_text("3.11\n", encoding="utf-8")

    monkeypatch.setattr(python_rt, "RUNTIMES_DIR", runtimes_dir)
    monkeypatch.chdir(tmp_path)

    assert selected_version("python") == "3.11"
    assert tools.resolve("pip") == str(py311_bin / "pip")
