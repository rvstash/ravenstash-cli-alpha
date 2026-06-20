"""`rvn runtime` command group."""

from __future__ import annotations

import platform
import shutil
from pathlib import Path

import typer

from .. import output
from . import java as java_rt
from . import node as node_rt
from . import python as python_rt
from ._install import ENV_FILE, is_debian, write_env_file
from .selection import selected_version


app = typer.Typer(
    name="runtime",
    help="Install and manage local Python, Node.js, and Java runtimes.",
    no_args_is_help=True,
)

_KINDS = ("python", "node", "java")


def _require_supported_platform() -> None:
    if platform.system().lower() != "linux":
        output.fatal("rvn runtime install currently supports Linux only.")


def _finder(kind: str):
    return {
        "python": python_rt.find,
        "node": node_rt.find,
        "java": java_rt.find,
    }[kind]


def _lister(kind: str):
    return {
        "python": python_rt.list_installed,
        "node": node_rt.list_installed,
        "java": java_rt.list_installed,
    }[kind]


def _installer(kind: str):
    return {
        "python": python_rt.install,
        "node": node_rt.install,
        "java": java_rt.install,
    }[kind]


@app.command("install")
def install(
    kind: str = typer.Argument(..., help="Runtime kind: python | node | java"),
    version: str = typer.Argument(
        ...,
        help="Version to install. Examples: 3.12, 22, 21",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Remove an existing matching installation and download again.",
    ),
) -> None:
    """Install a runtime into the rvn-managed store under ~/.rvn/runtimes."""
    if kind not in _KINDS:
        output.fatal(f"Unknown runtime kind '{kind}'. Choose from: {', '.join(_KINDS)}")

    _require_supported_platform()
    if not is_debian():
        output.warn(
            "This system does not appear to be Debian/Ubuntu based. "
            "Proceeding with portable Linux binaries."
        )

    if force:
        existing = _finder(kind)(version)
        if existing:
            output.info(f"Removing {existing} ...")
            shutil.rmtree(existing)

    _installer(kind)(version)


@app.command("uninstall")
def uninstall(
    kind: str = typer.Argument(..., help="Runtime kind: python | node | java"),
    version: str = typer.Argument(..., help="Installed version or version prefix."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Remove a runtime from the rvn-managed store."""
    if kind not in _KINDS:
        output.fatal(f"Unknown runtime kind '{kind}'. Choose from: {', '.join(_KINDS)}")

    existing = _finder(kind)(version)
    if not existing:
        output.fatal(f"No installed {kind} runtime matches '{version}'.")
    if not yes:
        typer.confirm(f"Remove {kind} runtime at {existing}?", abort=True)
    shutil.rmtree(existing)
    output.success(f"Removed {kind} runtime '{version}'.")


@app.command("list")
def list_runtimes() -> None:
    """List runtimes installed by rvn."""
    rows: list[list[str]] = []
    for kind in _KINDS:
        for ver, path in _lister(kind)():
            rows.append([kind, ver, str(path)])

    if not rows:
        output.info("No runtimes installed. Run: rvn runtime install <kind> <version>")
        return

    output.table(["Kind", "Version", "Path"], rows, title="rvn-managed runtimes")


@app.command("which")
def which(
    kind: str = typer.Argument(..., help="Runtime kind: python | node | java"),
    version: str = typer.Argument("", help="Version prefix (optional)."),
) -> None:
    """Print the binary path of an installed runtime."""
    if kind not in _KINDS:
        output.fatal(f"Unknown runtime kind '{kind}'. Choose from: {', '.join(_KINDS)}")

    binary_rel = {
        "python": "bin/python3",
        "node": "bin/node",
        "java": "bin/java",
    }[kind]
    requested_version = version or selected_version(kind) or ""
    base = _finder(kind)(requested_version)
    if base is None:
        output.fatal(
            f"No installed {kind} matches '{requested_version}'.\n"
            f"  Install with: rvn runtime install {kind} {requested_version or '<version>'}"
        )

    binary = base / binary_rel
    typer.echo(str(binary) if binary.exists() else str(base))


@app.command("use")
def use(
    kind: str = typer.Argument(..., help="Runtime kind: python | node | java"),
    version: str = typer.Argument(..., help="Installed version or version prefix."),
) -> None:
    """Pin a runtime version for the current project."""
    if kind not in _KINDS:
        output.fatal(f"Unknown runtime kind '{kind}'. Choose from: {', '.join(_KINDS)}")

    base = _finder(kind)(version)
    if base is None:
        output.fatal(
            f"No installed {kind} matches '{version}'.\n"
            f"  Install with: rvn runtime install {kind} {version}"
        )

    version_name = base.name
    marker = {
        "python": ".python-version",
        "node": ".node-version",
        "java": ".java-version",
    }[kind]
    Path(marker).write_text(version_name + "\n", encoding="utf-8")
    output.success(f"Pinned {kind} {version_name} in {marker}.")


@app.command("env")
def env() -> None:
    """Print the shell snippet that adds rvn runtime shims to PATH."""
    write_env_file()
    typer.echo(ENV_FILE.read_text(encoding="utf-8"), nl=False)


@app.command("setup-shell")
def setup_shell(
    shell: str | None = typer.Option(
        None,
        "--shell",
        help="Shell: bash | zsh | fish. Auto-detected from $SHELL if omitted.",
    ),
) -> None:
    """Add rvn's runtime shims to the user's shell startup file."""
    import os

    write_env_file()
    source_line = '. "$HOME/.rvn/env"'
    detected_shell = shell or Path(os.environ.get("SHELL", "")).name

    if detected_shell == "fish":
        fish_rc = Path.home() / ".config" / "fish" / "conf.d" / "rvn.fish"
        fish_rc.parent.mkdir(parents=True, exist_ok=True)
        fish_rc.write_text(
            '# rvn managed runtimes\nset -gx PATH "$HOME/.rvn/shims" $PATH\n',
            encoding="utf-8",
        )
        output.success(f"Written fish config to {fish_rc}")
        return

    if detected_shell == "zsh":
        rc_candidates = [Path.home() / ".zshrc"]
    elif detected_shell == "bash":
        rc_candidates = [Path.home() / ".bashrc", Path.home() / ".bash_profile"]
    else:
        rc_candidates = [
            p
            for p in (
                Path.home() / ".bashrc",
                Path.home() / ".bash_profile",
                Path.home() / ".zshrc",
                Path.home() / ".profile",
            )
            if p.exists()
        ] or [Path.home() / ".bashrc"]

    added: list[str] = []
    for rc in rc_candidates:
        content = rc.read_text(encoding="utf-8") if rc.exists() else ""
        if source_line in content:
            output.info(f"Already configured in {rc}")
            continue
        with rc.open("a", encoding="utf-8") as fh:
            fh.write(f"\n# rvn managed runtimes\n{source_line}\n")
        added.append(str(rc))

    if added:
        output.success(f"Added rvn env source to: {', '.join(added)}")
        output.info("Restart your shell or run: source ~/.rvn/env")
    else:
        output.info("Already configured; no changes made.")


@app.command("doctor")
def doctor() -> None:
    """Show local runtime manager status."""
    rows: list[list[str]] = []
    for kind, binary in (("python", "python3"), ("node", "node"), ("java", "java")):
        managed = _finder(kind)("")
        system = shutil.which(binary)
        rows.append(
            [
                kind,
                str(managed) if managed else "none",
                system or "not found",
            ]
        )
    output.table(["Runtime", "rvn-managed", "System PATH"], rows, title="Runtime status")
