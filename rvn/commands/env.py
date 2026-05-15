"""rvn venv — create or manage a project virtual environment.

Mirrors uv's ``uv venv`` experience:

    rvn venv                create .venv using uv (or stdlib venv)
    rvn venv .env           create at a custom path
    rvn venv --python 3.12  pin a specific Python version
    rvn venv --show         print the path to the active/found venv

For Node and Java, this command prints clear guidance (no true venv concept
exists, but the equivalent setup is explained).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import typer

from .. import manifest as mf
from .. import output


app = typer.Typer(
    name="venv",
    help="Create a virtual environment in the project directory.",
    no_args_is_help=False,
)


def _find_venv(cwd: Path) -> Path | None:
    """Return the path of the first venv-looking directory under *cwd*."""
    for candidate in (".venv", "venv", ".env", "env"):
        p = cwd / candidate
        if (p / "pyvenv.cfg").exists():
            return p
    return None


@app.callback(invoke_without_command=True)
def venv(
    path: Path = typer.Argument(
        Path(".venv"),
        help="Where to create the virtual environment (default: .venv).",
    ),
    python: str | None = typer.Option(
        None,
        "--python",
        "-p",
        help="Python version to use, e.g. 3.12 (requires uv or pyenv).",
    ),
    show: bool = typer.Option(
        False, "--show", help="Print the path of the existing venv and exit."
    ),
    directory: Path = typer.Option(
        Path("."),
        "--directory",
        "-C",
        help="Project root (default: cwd).",
    ),
) -> None:
    """Create a virtual environment for the current project.

    \b
    Examples:
        rvn venv                     # create .venv with default Python
        rvn venv --python 3.12       # create .venv with Python 3.12 (needs uv)
        rvn venv myenv               # create at myenv/
        rvn venv --show              # print path of detected venv

    For Node projects, node_modules serves as the local environment — run
    ``rvn sync`` (or ``rvn node sync``) to install packages.

    For Java/Maven projects, dependencies are cached in ``~/.m2``.  Run
    ``rvn sync`` (or ``rvn java sync``) to resolve them.
    """
    cwd = directory.resolve()
    info = mf.detect(cwd)

    if info and info.eco == "node":
        output.info(
            "Node projects use node_modules/ as the local environment.\n"
            "Run `rvn sync` (or `npm install`) to install dependencies."
        )
        raise typer.Exit()

    if info and info.eco == "java":
        output.info(
            "Java/Maven projects cache dependencies in ~/.m2/repository.\n"
            "Run `rvn sync` (or `mvn dependency:resolve`) to pre-fetch them."
        )
        raise typer.Exit()

    if show:
        found = _find_venv(cwd)
        if found:
            typer.echo(str(found))
        else:
            output.warn("No virtual environment found in current directory.")
        raise typer.Exit()

    target = path if path.is_absolute() else cwd / path

    if shutil.which("uv"):
        cmd = ["uv", "venv", str(target)]
        if python:
            cmd.extend(["--python", python])
        output.info(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
    else:
        if python:
            output.warn(
                f"--python {python} requires uv.  "
                "Install uv (https://docs.astral.sh/uv/) or use pyenv to manage versions."
            )
        cmd = [sys.executable, "-m", "venv", str(target)]
        output.info(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)

    output.success(f"Virtual environment created at {target}")
    output.info(f"Activate with:  source {target}/bin/activate")
