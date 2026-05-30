"""rvn — root CLI entrypoint.

Registers all subcommand groups and provides the global --profile and
--version flags.

Command surface
---------------
rvn login / rvn auth / rvn config / rvn repos / rvn packages / rvn tokens
    Account, config, auth, and management commands.

rvn sync / rvn venv / rvn add / rvn remove
    Universal project lifecycle commands (auto-detect Python / Node / Java).

rvn pypi / rvn npm / rvn maven
    Full registry ecosystem groups: install/publish/deploy, yank, deprecate, bump,
    dist-tags (ls/add/rm), snapshots (publish/ls), and registry URL helpers.

rvn python / rvn node / rvn java
    Slim runtime management: pin (install runtime version) + venv (Python only).

rvn pkg
    Universal publish/install with automatic kind detection.

rvn run <tool> [args...]
    Transparent native tool runner — runs pip / uv / npm / yarn / pnpm /
    mvn / gradle / sbt with the private registry injected automatically.
"""

from __future__ import annotations

import typer

from .commands import auth, config, login, packages, pkg, repos, tokens
from .commands.add_remove import add_app, remove_app
from .commands.env import app as venv_app
from .commands.maven_eco import app as maven_eco_app
from .commands.npm_eco import app as npm_eco_app
from .commands.pypi_eco import app as pypi_eco_app
from .commands.run import run_tool
from .commands.runtime import java_app, node_app, python_app
from .commands.sync import app as sync_app
from .commands.system import app as system_app


app = typer.Typer(
    name="rvn",
    help="Universal package manager CLI for Ravenstash private registries.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

# ── Management commands ───────────────────────────────────────────────────────
app.add_typer(login.app, name="login")
app.add_typer(auth.app, name="auth")
app.add_typer(config.app, name="config")
app.add_typer(repos.app, name="repos")
app.add_typer(packages.app, name="packages")
app.add_typer(tokens.app, name="tokens")

# ── Universal project lifecycle ───────────────────────────────────────────────
app.add_typer(
    sync_app, name="sync", help="Sync all project deps from manifest (auto-detects type)."
)
app.add_typer(venv_app, name="venv", help="Create a virtual environment for the project.")
app.add_typer(add_app, name="add", help="Add a dependency to the manifest and install it.")
app.add_typer(remove_app, name="remove", help="Remove a dependency from the manifest.")

# ── Registry ecosystem groups (full lifecycle + registry ops) ─────────────────
app.add_typer(
    pypi_eco_app,
    name="pypi",
    help="PyPI registry — install, publish, yank, bump, dist-tags, snapshots.",
)
app.add_typer(
    npm_eco_app,
    name="npm",
    help="npm registry — install, publish, deprecate, yank, bump, dist-tags, snapshots.",
)
app.add_typer(
    maven_eco_app,
    name="maven",
    help="Maven registry — install, deploy, yank, deprecate, bump, dist-tags, snapshots.",
)

# ── Runtime management (slim — pin only) ──────────────────────────────────────
app.add_typer(
    python_app,
    name="python",
    help="Python runtime — pin versions (uv / pyenv / built-in) and create virtual environments.",
)
app.add_typer(
    node_app, name="node", help="Node.js runtime — pin versions (fnm / volta / built-in)."
)
app.add_typer(
    java_app, name="java", help="Java runtime — pin versions (SDKMAN / Temurin built-in)."
)

# ── System runtime management (download + install) ────────────────────────────
app.add_typer(
    system_app,
    name="system",
    help="Install/manage runtimes (Python, Node, Java, Maven) — no system tools required.",
)

# ── Universal detect + publish/install ────────────────────────────────────────
app.add_typer(
    pkg.app, name="pkg", help="Universal publish/install — auto-detects PyPI / npm / Maven."
)

# ── Transparent tool runner ───────────────────────────────────────────────────
app.command(
    "run",
    help="Run pip / uv / npm / yarn / pnpm / mvn / gradle with private registry injected.",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    add_help_option=True,
)(run_tool)


# ── Top-level version command ─────────────────────────────────────────────────


@app.command("version")
def project_version(
    bump: str | None = typer.Option(None, "--bump", help="major | minor | patch"),
    directory: str | None = typer.Option(None, "--directory", "-C", help="Project directory."),
) -> None:
    """Display (or bump) the project version — auto-detects pyproject.toml / package.json / pom.xml.

    Halts with an error when more than one manifest kind is detected to avoid
    ambiguity.  Use the stack-specific commands instead:

    \b
        rvn pypi version
        rvn npm version
        rvn maven version

    Examples:

    \b
        rvn version                            # show project version
        rvn version --bump patch               # bump in-place
        rvn version -C /path/to/project        # explicit directory
    """
    from pathlib import Path as _Path

    from . import output
    from .detect import detect_all_kinds

    cwd = (_Path(directory) if directory else _Path(".")).resolve()
    kinds = detect_all_kinds(cwd)

    if len(kinds) > 1:
        cmds = " / ".join(f"rvn {k} version" for k in kinds)
        output.fatal(
            f"Ambiguous project — found manifests for: {', '.join(kinds)}.\n"
            f"  Use the stack-specific command instead:\n"
            f"  {cmds}"
        )

    if not kinds:
        output.fatal(
            "No project manifest found (pyproject.toml / package.json / pom.xml).\n"
            "  Run this command from a project directory."
        )

    kind = kinds[0]

    # Delegate to the appropriate stack version command.
    if kind == "pypi":
        from .commands.pypi_eco import pypi_version

        pypi_version(bump=bump, directory=cwd)  # type: ignore[arg-type]
    elif kind == "npm":
        from .commands.npm_eco import npm_version

        npm_version(bump=bump, no_git_tag=False, directory=cwd)  # type: ignore[arg-type]
    elif kind == "maven":
        from .commands.maven_eco import maven_version

        maven_version(bump=bump, directory=cwd)  # type: ignore[arg-type]


# ── Top-level callbacks ───────────────────────────────────────────────────────


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import PackageNotFoundError, version

        try:
            v = version("rvn")
        except PackageNotFoundError:
            v = "dev"
        typer.echo(f"rvn {v}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Print version and exit.",
    ),
) -> None:
    """rvn — Unified package manager for Ravenstash private registries.

    Covers Python, Node.js, and Java/Maven — project lifecycle and registry
    operations in one tool, modelled on uv's clean command surface.

    \b
    Quick start:
        rvn auth login                          # authenticate
        rvn repos list                          # list repositories

    \b
    Universal project commands (auto-detect type from manifest):
        rvn sync                                # install all deps (uv/npm/mvn)
        rvn venv                                # create .venv (Python)
        rvn add requests>=2.28                  # add dep + install
        rvn add lodash@4                        # → npm
        rvn add com.google.guava:guava:33.0     # → Maven
        rvn remove requests                     # remove dep from manifest

    \b
    Registry ecosystems (full lifecycle: install / publish / yank / bump / dist-tags / snapshots):
        rvn pypi  install / publish / yank / bump / dist-tag / snapshot / index-url
        rvn npm   install / publish / deprecate / yank / bump / dist-tag / snapshot / registry-url
        rvn maven install / deploy / yank / deprecate / bump / dist-tag / snapshot / repo-url

    \b
    Runtime management (pin a version, create venvs):
        rvn python pin 3.14                     # uv python install 3.14
        rvn python venv                         # create .venv
        rvn node   pin 20                       # fnm / volta install node@20
        rvn java   pin 21                       # sdk install java 21

    \b
    Multi-registry auth:
        rvn auth login                          # interactive login
        rvn auth add-registry --kind npm --repo my-npm
        rvn auth list                           # show all profiles + per-kind overrides
        rvn auth status                         # verify token

    \b
    Native tool passthrough (injects private registry automatically):
        rvn run uv sync
        rvn run pip install requests
        rvn run npm install lodash
        rvn run mvn clean install
    """
