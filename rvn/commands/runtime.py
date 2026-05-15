"""rvn python / rvn node / rvn java — runtime version management only.

These slim typer apps expose only the `pin` command (and `venv` for Python).
Full ecosystem lifecycle (install, publish, sync, add, remove, etc.) is in
the dedicated rvn pypi / rvn npm / rvn maven commands.

    rvn python pin 3.14          # install Python 3.14 via uv / pyenv
    rvn python venv              # create .venv
    rvn node   pin 20            # install Node 20 via fnm / volta
    rvn java   pin 21            # install Java 21 via SDKMAN
    rvn java   pin 21 --dist tem # install Temurin distribution
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import typer

from .. import output


# ── Python runtime ────────────────────────────────────────────────────────────

python_app = typer.Typer(
    name="python",
    help="Python runtime — install and pin versions.",
    no_args_is_help=True,
)


@python_app.command("pin")
def python_pin(
    version: str = typer.Argument(..., help="Python version, e.g. 3.12 or 3.13.0."),
    write_file: bool = typer.Option(
        True,
        "--write-file/--no-write-file",
        help="Write .python-version to pin for the project.",
    ),
) -> None:
    """Install a Python runtime version and pin it for the project.

    Uses uv python install (preferred) or pyenv install as a fallback.

    \b
        rvn python pin 3.12
        rvn python pin 3.13.0
        rvn python pin 3.14 --no-write-file
    """
    if shutil.which("uv"):
        output.info(f"Running: uv python install {version}")
        subprocess.run(["uv", "python", "install", version], check=True)
        if write_file:
            Path(".python-version").write_text(version + "\n")
            output.info("Wrote .python-version")
    elif shutil.which("pyenv"):
        output.info(f"Running: pyenv install {version} --skip-existing")
        subprocess.run(["pyenv", "install", version, "--skip-existing"], check=True)
        subprocess.run(["pyenv", "local", version], check=True)
        output.info("Wrote .python-version via pyenv")
    else:
        output.info(
            "uv/pyenv not found — using rvn built-in runtime manager (python-build-standalone)."
        )
        from ..runtimes import python as python_rt

        python_rt.install(version)
        if write_file:
            Path(".python-version").write_text(version + "\n")
            output.info("Wrote .python-version")

    output.success(f"Python {version} ready.")


@python_app.command("venv")
def python_venv(
    path: Path = typer.Argument(Path(".venv"), help="Venv path (default: .venv)."),
    python_version: str | None = typer.Option(
        None, "--python", "-p", help="Python version, e.g. 3.12."
    ),
    show: bool = typer.Option(False, "--show", help="Print path of existing venv."),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
) -> None:
    """Create a Python virtual environment.

    \b
        rvn python venv               # create .venv
        rvn python venv --python 3.12 # create with Python 3.12 (requires uv)
        rvn python venv myenv         # create at myenv/
        rvn python venv --show        # print path of detected venv
    """
    cwd = directory.resolve()

    if show:
        for candidate in (".venv", "venv", ".env", "env"):
            p = cwd / candidate
            if (p / "pyvenv.cfg").exists():
                typer.echo(str(p))
                return
        output.warn("No virtual environment found.")
        raise typer.Exit(1)

    target = path if path.is_absolute() else cwd / path

    if shutil.which("uv"):
        cmd = ["uv", "venv", str(target)]
        if python_version:
            cmd.extend(["--python", python_version])
    else:
        if python_version:
            output.warn("--python requires uv.  Install uv or use pyenv.")
        cmd = [sys.executable, "-m", "venv", str(target)]

    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    output.success(f"Virtual environment created at {target}")
    output.info(f"Activate with:  source {target}/bin/activate")


# ── Node.js runtime ───────────────────────────────────────────────────────────

node_app = typer.Typer(
    name="node",
    help="Node.js runtime — install and pin versions.",
    no_args_is_help=True,
)


@node_app.command("pin")
def node_pin(
    version: str = typer.Argument(..., help="Node.js version, e.g. 20 or 20.11.0."),
    write_file: bool = typer.Option(
        True,
        "--write-file/--no-write-file",
        help="Write .nvmrc / .node-version.",
    ),
) -> None:
    """Install a Node.js runtime version and pin it for the project.

    Uses volta, fnm, or nvm (detected in that order).

    \b
        rvn node pin 20
        rvn node pin 20.11.0
        rvn node pin 22 --no-write-file
    """
    if shutil.which("volta"):
        output.info(f"Running: volta install node@{version}")
        subprocess.run(["volta", "install", f"node@{version}"], check=True)
        output.success(f"Node {version} installed via volta.")
    elif shutil.which("fnm"):
        output.info(f"Running: fnm install {version}")
        subprocess.run(["fnm", "install", version], check=True)
        if write_file:
            Path(".node-version").write_text(version + "\n")
            output.info("Wrote .node-version")
        output.success(f"Node {version} installed via fnm.")
    else:
        output.info("volta/fnm not found — using rvn built-in runtime manager (nodejs.org).")
        from ..runtimes import node as node_rt

        node_rt.install(version)
        if write_file:
            Path(".nvmrc").write_text(version + "\n")
            output.info("Wrote .nvmrc")
        output.success(f"Node {version} ready.")


# ── Java runtime ──────────────────────────────────────────────────────────────

java_app = typer.Typer(
    name="java",
    help="Java runtime — install and pin versions via SDKMAN.",
    no_args_is_help=True,
)


@java_app.command("pin")
def java_pin(
    version: str = typer.Argument(..., help="Java version, e.g. '21' or '21.0.3-tem'."),
    distribution: str | None = typer.Option(
        None,
        "--dist",
        "-d",
        help="SDKMAN distribution, e.g. 'graalce', 'tem', 'zulu'.",
    ),
    write_file: bool = typer.Option(
        True,
        "--write-file/--no-write-file",
        help="Write .java-version.",
    ),
) -> None:
    """Install a Java runtime via SDKMAN and pin it for the project.

    \b
        rvn java pin 21
        rvn java pin 21.0.3 --dist tem
        rvn java pin 21.0.3-graalce
        rvn java pin 17 --no-write-file

    Requires SDKMAN (https://sdkman.io/).
    """
    sdk_version = f"{version}.{distribution}" if distribution else version

    if shutil.which("sdk"):
        output.info(f"Running: sdk install java {sdk_version}")
        script = f'source "$HOME/.sdkman/bin/sdkman-init.sh" && sdk install java {sdk_version}'
        result = subprocess.run(["bash", "-c", script], check=False)
        if result.returncode not in (0, 1):  # sdk returns 1 when already installed
            output.warn(f"sdk install exited with code {result.returncode}")
        if write_file:
            Path(".java-version").write_text(version + "\n")
            output.info("Wrote .java-version")
        output.success(f"Java {sdk_version} ready.")
    else:
        output.info("SDKMAN not found — using rvn built-in runtime manager (Eclipse Temurin).")
        from ..runtimes import java as java_rt

        java_rt.install(version)
        if write_file:
            Path(".java-version").write_text(version + "\n")
            output.info("Wrote .java-version")
        output.success(f"Java {version} ready.")
