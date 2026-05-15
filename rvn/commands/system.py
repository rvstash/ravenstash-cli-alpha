"""rvn system — manage rvn-installed runtimes (Python, Node.js, Java, Maven).

Installs isolated, self-contained runtime versions into ~/.rvn/runtimes/
without touching system paths, apt packages, or any existing runtime manager.

    rvn system install python 3.14
    rvn system install node 20
    rvn system install java 21
    rvn system install maven 3.9.6
    rvn system install maven latest

    rvn system list
    rvn system which python 3.14
    rvn system env
    rvn system setup-shell
"""

from __future__ import annotations

import platform
import shutil
from pathlib import Path

import typer

from .. import output
from ..runtimes import java as java_rt
from ..runtimes import maven as maven_rt
from ..runtimes import node as node_rt
from ..runtimes import python as python_rt
from ..runtimes._install import ENV_FILE, is_debian, write_env_file


app = typer.Typer(
    name="system",
    help="Manage rvn-installed runtimes (Python, Node.js, Java, Maven).",
    no_args_is_help=True,
)

_KINDS = ("python", "node", "java", "maven")


def _require_linux() -> None:
    if platform.system().lower() != "linux":
        output.fatal("rvn system install only supports Linux.")


# ── install ───────────────────────────────────────────────────────────────────


@app.command("install")
def system_install(
    kind: str = typer.Argument(
        ...,
        help="Runtime kind: python | node | java | maven",
    ),
    version: str = typer.Argument(
        "latest",
        help="Version to install (default: latest). Examples: 3.14, 20, 21, 3.9.6",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Remove existing installation and re-download.",
    ),
) -> None:
    """Install a runtime into the rvn-managed store (~/.rvn/runtimes/).

    Downloads a pre-built binary without touching system packages or any
    existing runtime manager (uv, nvm, SDKMAN, etc.).  Safe to run
    alongside an existing system installation.

    Supported on Linux x86_64 and aarch64 (tested on Debian/Ubuntu).

    \b
        rvn system install python 3.14
        rvn system install node 20
        rvn system install node latest
        rvn system install java 21
        rvn system install maven 3.9.6
        rvn system install maven latest
    """
    if kind not in _KINDS:
        output.fatal(f"Unknown runtime kind '{kind}'. Choose from: {', '.join(_KINDS)}")

    _require_linux()

    if not is_debian():
        output.warn(
            "This system does not appear to be Debian/Ubuntu based. "
            "Proceeding — binaries are portable across Linux distributions."
        )

    if kind == "python":
        if force:
            existing = python_rt.find(version)
            if existing:
                output.info(f"Removing {existing} ...")
                shutil.rmtree(existing)
        python_rt.install(version)

    elif kind == "node":
        if force:
            existing = node_rt.find(version)
            if existing:
                output.info(f"Removing {existing} ...")
                shutil.rmtree(existing)
        node_rt.install(version)

    elif kind == "java":
        if force:
            existing = java_rt.find(version)
            if existing:
                output.info(f"Removing {existing} ...")
                shutil.rmtree(existing)
        java_rt.install(version)

    elif kind == "maven":
        if force:
            existing = maven_rt.find(version)
            if existing:
                output.info(f"Removing {existing} ...")
                shutil.rmtree(existing)
        maven_rt.install(version)


# ── list ──────────────────────────────────────────────────────────────────────


@app.command("list", help="List all runtimes installed in the rvn-managed store.")
def system_list() -> None:
    """Show every runtime version installed by rvn system install.

    \b
        rvn system list
    """
    rows: list[list[str]] = []
    for kind, lister in (
        ("python", python_rt.list_installed),
        ("node", node_rt.list_installed),
        ("java", java_rt.list_installed),
        ("maven", maven_rt.list_installed),
    ):
        for ver, path in lister():
            rows.append([kind, ver, str(path)])

    if not rows:
        output.info("No runtimes installed.  Run: rvn system install <kind> <version>")
        return

    output.table(["Kind", "Version", "Path"], rows, title="rvn-managed runtimes")


# ── which ─────────────────────────────────────────────────────────────────────


@app.command("which")
def system_which(
    kind: str = typer.Argument(..., help="Runtime kind: python | node | java | maven"),
    version: str = typer.Argument("", help="Version prefix (optional)."),
) -> None:
    """Print the binary path of an installed runtime.

    \b
        rvn system which python 3.14
        rvn system which node 20
        rvn system which java 21
        rvn system which maven
    """
    bin_rel = {
        "python": "bin/python3",
        "node": "bin/node",
        "java": "bin/java",
        "maven": "bin/mvn",
    }
    finders: dict[str, object] = {
        "python": python_rt.find,
        "node": node_rt.find,
        "java": java_rt.find,
        "maven": maven_rt.find,
    }
    if kind not in finders:
        output.fatal(f"Unknown kind '{kind}'. Choose from: {', '.join(_KINDS)}")

    base = finders[kind](version)  # type: ignore[operator]
    if base is None:
        output.fatal(
            f"No installed {kind} matches '{version}'.\n"
            f"  Install with: rvn system install {kind} {version or '<version>'}"
        )

    binary = base / bin_rel[kind]
    typer.echo(str(binary) if binary.exists() else str(base))


# ── env ───────────────────────────────────────────────────────────────────────


@app.command("env")
def system_env() -> None:
    """Print the rvn shell environment snippet.

    Source this file in your shell RC to add rvn shims to PATH.

    \b
        rvn system env
        rvn system env >> ~/.bashrc    # append manually
    """
    write_env_file()
    typer.echo(ENV_FILE.read_text())


# ── setup-shell ───────────────────────────────────────────────────────────────


@app.command("setup-shell")
def system_setup_shell(
    shell: str | None = typer.Option(
        None,
        "--shell",
        help="Shell: bash | zsh | fish. Auto-detected from $SHELL if omitted.",
    ),
) -> None:
    """Append `source ~/.rvn/env` to your shell RC file (run once after install).

    This adds ``~/.rvn/shims`` to PATH so rvn-managed runtimes are found
    automatically.  Existing entries are not duplicated.

    \b
        rvn system setup-shell
        rvn system setup-shell --shell zsh
        rvn system setup-shell --shell fish
    """
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

    rc_candidates: list[Path] = []
    if detected_shell == "zsh":
        rc_candidates = [Path.home() / ".zshrc"]
    elif detected_shell == "bash":
        rc_candidates = [Path.home() / ".bashrc", Path.home() / ".bash_profile"]
    else:
        # Auto-detect by checking which RC files exist
        for name in (".bashrc", ".bash_profile", ".zshrc", ".profile"):
            p = Path.home() / name
            if p.exists():
                rc_candidates.append(p)
        if not rc_candidates:
            rc_candidates = [Path.home() / ".bashrc"]

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
        output.info("Restart your shell or run:  source ~/.rvn/env")
    else:
        output.info("Already configured — no changes made.")
