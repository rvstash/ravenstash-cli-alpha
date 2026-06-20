from __future__ import annotations

from typing import TYPE_CHECKING

from rvn.runtime import _install
from rvn.runtime import commands as runtime_cmd
from rvn.runtime import java as java_rt
from rvn.runtime import node as node_rt
from rvn.runtime import python as python_rt
from typer.testing import CliRunner


if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


def _point_runtime_dirs(monkeypatch, runtimes_dir: Path) -> None:
    monkeypatch.setattr(python_rt, "RUNTIMES_DIR", runtimes_dir)
    monkeypatch.setattr(node_rt, "RUNTIMES_DIR", runtimes_dir)
    monkeypatch.setattr(java_rt, "RUNTIMES_DIR", runtimes_dir)


def test_runtime_list_displays_all_managed_runtimes(monkeypatch, tmp_path: Path) -> None:
    runtimes_dir = tmp_path / "runtimes"
    _point_runtime_dirs(monkeypatch, runtimes_dir)
    (runtimes_dir / "python" / "3.12.3").mkdir(parents=True)
    (runtimes_dir / "node" / "24.14.1").mkdir(parents=True)
    (runtimes_dir / "java" / "21.0.3+9").mkdir(parents=True)

    result = runner.invoke(runtime_cmd.app, ["list"])

    assert result.exit_code == 0
    assert "python" in result.output
    assert "3.12.3" in result.output
    assert "node" in result.output
    assert "24.14.1" in result.output
    assert "java" in result.output
    assert "21.0.3+9" in result.output


def test_runtime_which_uses_project_pinned_node_version(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtimes_dir = tmp_path / "runtimes"
    node_bin = runtimes_dir / "node" / "24.14.1" / "bin"
    node_bin.mkdir(parents=True)
    (node_bin / "node").write_text("", encoding="utf-8")
    (tmp_path / ".node-version").write_text("24\n", encoding="utf-8")
    _point_runtime_dirs(monkeypatch, runtimes_dir)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(runtime_cmd.app, ["which", "node"])

    assert result.exit_code == 0
    assert result.output.strip() == str(node_bin / "node")


def test_runtime_use_writes_marker_for_resolved_full_version(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtimes_dir = tmp_path / "runtimes"
    (runtimes_dir / "java" / "21.0.3+9").mkdir(parents=True)
    _point_runtime_dirs(monkeypatch, runtimes_dir)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(runtime_cmd.app, ["use", "java", "21"])

    assert result.exit_code == 0
    assert (tmp_path / ".java-version").read_text(encoding="utf-8") == "21.0.3+9\n"
    assert "Pinned java 21.0.3+9" in result.output


def test_runtime_uninstall_removes_matching_runtime_with_yes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtimes_dir = tmp_path / "runtimes"
    runtime_dir = runtimes_dir / "python" / "3.12.3"
    runtime_dir.mkdir(parents=True)
    _point_runtime_dirs(monkeypatch, runtimes_dir)

    result = runner.invoke(runtime_cmd.app, ["uninstall", "python", "3.12", "--yes"])

    assert result.exit_code == 0
    assert not runtime_dir.exists()
    assert "Removed python runtime '3.12'" in result.output


def test_runtime_install_rejects_unknown_kind() -> None:
    result = runner.invoke(runtime_cmd.app, ["install", "ruby", "3.3"])

    assert result.exit_code == 1
    assert "Unknown runtime kind 'ruby'" in result.stderr


def test_runtime_env_uses_patched_env_file(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / "env"

    def write_fake_env() -> None:
        env_file.write_text("export RVN_HOME=/tmp/rvn\n", encoding="utf-8")

    monkeypatch.setattr(runtime_cmd, "ENV_FILE", env_file)
    monkeypatch.setattr(runtime_cmd, "write_env_file", write_fake_env)

    result = runner.invoke(runtime_cmd.app, ["env"])

    assert result.exit_code == 0
    assert result.output == "export RVN_HOME=/tmp/rvn\n"


def test_runtime_doctor_reports_managed_and_system_paths(monkeypatch, tmp_path: Path) -> None:
    runtimes_dir = tmp_path / "runtimes"
    python_dir = runtimes_dir / "python" / "3.12.3"
    python_dir.mkdir(parents=True)
    _point_runtime_dirs(monkeypatch, runtimes_dir)
    monkeypatch.setattr(runtime_cmd.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    captured: dict[str, list[list[str]]] = {}
    monkeypatch.setattr(
        runtime_cmd.output,
        "table",
        lambda columns, rows, title=None: captured.update({"rows": rows}),
    )

    result = runner.invoke(runtime_cmd.app, ["doctor"])

    assert result.exit_code == 0
    assert captured["rows"][0] == ["python", str(python_dir), "/usr/bin/python3"]
    assert captured["rows"][1] == ["node", "none", "/usr/bin/node"]
    assert captured["rows"][2] == ["java", "none", "/usr/bin/java"]


def test_write_shim_and_env_file_use_configured_rvn_dirs(monkeypatch, tmp_path: Path) -> None:
    rvn_dir = tmp_path / ".rvn"
    shims_dir = rvn_dir / "shims"
    env_file = rvn_dir / "env"
    monkeypatch.setattr(_install, "RVN_DIR", rvn_dir)
    monkeypatch.setattr(_install, "SHIMS_DIR", shims_dir)
    monkeypatch.setattr(_install, "ENV_FILE", env_file)

    _install.write_shim("python3", tmp_path / "python3")
    _install.write_env_file()

    shim = shims_dir / "python3"
    assert shim.read_text(encoding="utf-8") == f'#!/bin/sh\nexec "{tmp_path / "python3"}" "$@"\n'
    assert shim.stat().st_mode & 0o755 == 0o755
    assert 'export RVN_HOME="$HOME/.rvn"' in env_file.read_text(encoding="utf-8")
