"""rvn python — Python ecosystem commands.

Extends the registry-focused 'rvn pypi' commands with project-lifecycle
operations that mirror uv's command surface:

    rvn python sync                     # uv sync (or pip install)
    rvn python venv [path]              # uv venv / python -m venv
    rvn python add requests>=2.28       # add to pyproject.toml + install
    rvn python remove requests          # remove from pyproject.toml
    rvn python pin 3.12                 # install Python 3.12 via uv / pyenv
    rvn python install requests         # install from private registry
    rvn python publish dist/            # publish to private PyPI
    rvn python index-url                # print the private index URL
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import typer

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import manifest as mf
from .. import output
from ..registries import pypi as pypi_reg
from ..routing import RoutingMode, get_router
from ..runtimes import tools
from ..semver import bump_semver, validate_bump_part


app = typer.Typer(
    name="python",
    help="Python ecosystem — project lifecycle + PyPI registry.",
    no_args_is_help=True,
)

# ── helpers ───────────────────────────────────────────────────────────────────


def _creds(profile: str | None, repo: str | None) -> tuple | None:
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile)
    slug = repo or cfg.registry_defaults("pypi").default_repo
    if not slug or not token:
        return None
    return p.api_url, slug, token


def _authed_index(base_url: str, token: str) -> str:
    """Embed __token__:<token> into a PyPI simple-index URL."""
    parsed = urlparse(base_url)
    return urlunparse(parsed._replace(netloc=f"__token__:{token}@{parsed.netloc}"))


def _env_with_index(base_url: str, token: str) -> dict:
    """Return an env dict with UV_EXTRA_INDEX_URL and PIP_EXTRA_INDEX_URL set."""
    authed = _authed_index(base_url, token)
    env = {**os.environ}
    existing = env.get("UV_EXTRA_INDEX_URL", "")
    env["UV_EXTRA_INDEX_URL"] = (existing + " " + authed).strip()
    env["PIP_EXTRA_INDEX_URL"] = authed
    return env


# ── sync ──────────────────────────────────────────────────────────────────────


@app.command("sync")
def python_sync(
    frozen: bool = typer.Option(
        True, "--frozen/--no-frozen", help="Require lock file to be up-to-date."
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    repo: str | None = typer.Option(
        None, "--repo", "-r", help="Override the default PyPI repository slug."
    ),
    no_inject: bool = typer.Option(False, "--no-inject", help="Skip private registry injection."),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
    routing: RoutingMode = typer.Option(
        "canonical",
        "--routing",
        help="URL routing: canonical (default) | unified (not yet implemented).",
    ),
) -> None:
    """Sync Python dependencies from pyproject.toml or requirements.txt.

    Uses uv sync when available, falls back to pip.
    """
    cwd = directory.resolve()
    env = {**os.environ}

    if not no_inject:
        creds = _creds(profile, repo)
        if creds:
            api_url, slug, token = creds
            try:
                base_url = get_router(routing).pypi_index_url(api_url, slug)
            except NotImplementedError as exc:
                output.fatal(str(exc))
            env = _env_with_index(base_url, token)
        else:
            output.warn("No registry credentials — syncing from public index only.")

    info = mf.detect(cwd)
    if info is None or info.eco != "python":
        output.fatal("No Python manifest found (pyproject.toml or requirements.txt).")

    if info.kind == "pyproject":
        if tools.resolve("uv"):
            cmd = [tools.resolve("uv"), "sync"] + (["--frozen"] if frozen else [])  # type: ignore[list-item]
        else:
            cmd = [*tools.pip_cmd(), "install", "-e", "."]
    else:
        req = str(info.path)
        uv_path = tools.resolve("uv")
        if uv_path:
            cmd = [uv_path, "pip", "install", "-r", req]
        else:
            cmd = [*tools.pip_cmd(), "install", "-r", req]

    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)
    output.success("Sync complete.")


# ── venv ──────────────────────────────────────────────────────────────────────


@app.command("venv")
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

    uv_path = tools.resolve("uv")
    if uv_path:
        cmd = [uv_path, "venv", str(target)]
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


# ── add / remove ──────────────────────────────────────────────────────────────


@app.command("add")
def python_add(
    spec: str = typer.Argument(..., help="Package spec, e.g. 'requests>=2.28'."),
    dev: bool = typer.Option(False, "--dev", "-D", help="Add as optional/dev dependency."),
    no_sync: bool = typer.Option(False, "--no-sync", help="Update manifest only."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
    routing: RoutingMode = typer.Option(
        "canonical",
        "--routing",
        help="URL routing: canonical (default) | unified (not yet implemented).",
    ),
) -> None:
    """Add a Python dependency to pyproject.toml (or requirements.txt) and install it."""
    cwd = directory.resolve()
    info = mf.detect(cwd)
    if info is None or info.eco != "python":
        output.fatal("No Python manifest found.")

    changed = mf.add_dep(info, spec)
    if changed:
        output.success(f"Added '{spec}' to {info.path.name}")
    else:
        output.info(f"'{spec}' already present — spec updated if needed.")

    if no_sync:
        return

    env = {**os.environ}
    creds = _creds(profile, repo)
    if creds:
        api_url, slug, token = creds
        try:
            base_url = get_router(routing).pypi_index_url(api_url, slug)
        except NotImplementedError as exc:
            output.fatal(str(exc))
        env = _env_with_index(base_url, token)

    uv_path_add = tools.resolve("uv")
    if uv_path_add:
        cmd = [uv_path_add, "add", spec]
    else:
        cmd = [*tools.pip_cmd(), "install", spec]
    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


@app.command("remove")
def python_remove(
    name: str = typer.Argument(..., help="Package name to remove."),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
) -> None:
    """Remove a Python dependency from the manifest."""
    cwd = directory.resolve()
    info = mf.detect(cwd)
    if info is None or info.eco != "python":
        output.fatal("No Python manifest found.")

    removed = mf.remove_dep(info, name)
    if removed:
        output.success(f"Removed '{name}' from {info.path.name}")
        output.info("Run `rvn python sync` to update your environment.")
    else:
        output.warn(f"'{name}' not found in {info.path.name}")
        raise typer.Exit(1)


# ── pin ───────────────────────────────────────────────────────────────────────


@app.command("pin")
def python_pin(
    version: str = typer.Argument(..., help="Python version to install, e.g. 3.12 or 3.12.3."),
    write_file: bool = typer.Option(
        True, "--write-file/--no-write-file", help="Write .python-version to pin for the project."
    ),
) -> None:
    """Install a Python runtime version and pin it for the project.

    \b
    Uses uv python install (preferred) or pyenv install as a fallback.

        rvn python pin 3.12
        rvn python pin 3.13.0
    """
    uv_path_pin = tools.resolve("uv")
    if uv_path_pin:
        output.info(f"Running: uv python install {version}")
        subprocess.run([uv_path_pin, "python", "install", version], check=True)
        if write_file:
            Path(".python-version").write_text(version + "\n")
            output.info("Wrote .python-version")
    elif shutil.which("pyenv"):
        output.info(f"Running: pyenv install {version} --skip-existing")
        subprocess.run(["pyenv", "install", version, "--skip-existing"], check=True)
        subprocess.run(["pyenv", "local", version], check=True)
        output.info("Wrote .python-version via pyenv")
    else:
        output.warn(
            "No Python version manager found.  Install uv (https://docs.astral.sh/uv/) or pyenv."
        )
        if write_file:
            Path(".python-version").write_text(version + "\n")
            output.info(f"Wrote .python-version = {version} (runtime not installed)")
        raise typer.Exit(1)

    output.success(f"Python {version} ready.")


# ── install (from private registry) ──────────────────────────────────────────


@app.command("install")
def python_install(
    packages: list[str] = typer.Argument(..., help="Packages to install."),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository slug."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    tool: str = typer.Option("uv", "--tool", "-t", help="Install tool: uv (default) or pip."),
    routing: RoutingMode = typer.Option(
        "canonical",
        "--routing",
        help="URL routing: canonical (default) | unified (not yet implemented).",
    ),
) -> None:
    """Install Python packages from the private registry."""
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile)
    slug = repo or cfg.registry_defaults("pypi").default_repo
    if not slug:
        output.fatal(
            "No repository configured. Pass --repo or set a default with "
            "`rvn auth add-registry --kind pypi --repo <slug>`."
        )
    if not token:
        output.fatal("Not authenticated. Run `rvn auth login` first.")

    try:
        index_url = get_router(routing).pypi_index_url(p.api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))

    result = pypi_reg.install(
        index_url=index_url,
        token=token,
        packages=packages,
        tool=tool,
    )
    if not result:
        raise typer.Exit(1)


# ── publish ───────────────────────────────────────────────────────────────────


@app.command("publish")
def python_publish(
    dist_dir: Path = typer.Argument(Path("dist"), help="Directory with wheel/sdist files."),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository slug."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option(
        "canonical",
        "--routing",
        help="URL routing: canonical (default) | unified (not yet implemented).",
    ),
) -> None:
    """Publish wheel/sdist files to the private PyPI repository."""
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile)
    slug = repo or cfg.registry_defaults("pypi").default_repo
    if not slug:
        output.fatal("No repository configured.")
    if not token:
        output.fatal("Not authenticated. Run `rvn auth login`.")

    files = list(dist_dir.glob("*.whl")) + list(dist_dir.glob("*.tar.gz"))
    if not files:
        output.fatal(f"No .whl or .tar.gz files found in {dist_dir}")

    try:
        upload_url = get_router(routing).pypi_upload_url(p.api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    results = pypi_reg.publish(upload_url=upload_url, token=token, files=files)
    any_fail = False
    for r in results:
        if r.ok:
            output.success(f"Published {r.filename} ({r.version})")
        else:
            output.error(f"Failed {r.filename}: {r.detail}")
            any_fail = True
    if any_fail:
        raise typer.Exit(1)


# ── yank ─────────────────────────────────────────────────────────────────────


@app.command("yank")
def python_yank(
    package: str = typer.Argument(..., help="Package name."),
    version: str = typer.Argument(..., help="Version to yank."),
    reason: str | None = typer.Option(
        None, "--reason", "-m", help="Optional yank reason shown to installers."
    ),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository slug."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Mark a package version as yanked in the private PyPI registry.

    \b
    Yanked versions are hidden from version resolution but can still be
    installed when pinned exactly.  Conforms to PEP 592.

    \b
        rvn python yank my-pkg 1.2.3
        rvn python yank my-pkg 1.2.3 --reason "Contains a critical bug"
    """
    from ..client import ApiClient, ApiError

    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile)
    slug = repo or cfg.registry_defaults("pypi").default_repo
    if not slug:
        output.fatal(
            "No repository configured. Pass --repo or set a default with "
            "`rvn auth add-registry --kind pypi --repo <slug>`."
        )
    if not token:
        output.fatal("Not authenticated. Run `rvn auth login` first.")

    client = ApiClient(p.api_url, token)  # type: ignore[arg-type]
    body: dict | None = {"reason": reason} if reason else None
    try:
        client.post(
            f"/webapp/repository/{slug}/packages/{package}/versions/{version}/yank",
            json=body,
        )
        output.success(f"Yanked {package}=={version}.")
        if reason:
            output.info(f"Reason: {reason}")
    except ApiError as exc:
        output.fatal(str(exc))


# ── deprecate ─────────────────────────────────────────────────────────────────


@app.command("deprecate")
def python_deprecate(
    package: str = typer.Argument(..., help="Package name."),
    version: str = typer.Argument(..., help="Version to deprecate."),
    message: str = typer.Argument(..., help="Deprecation message."),
) -> None:
    """[Not supported] The PyPI protocol does not support deprecation.

    Use `rvn python yank` to prevent new installs of a specific version.
    """
    output.error(
        "The PyPI protocol does not support package deprecation.\n"
        "  Use `rvn python yank <package> <version>` to hide a version from resolvers."
    )
    raise typer.Exit(1)


# ── bump ──────────────────────────────────────────────────────────────────────


@app.command("bump")
def python_bump(
    part: str = typer.Argument(..., help="Version part to bump: major | minor | patch."),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
) -> None:
    """Bump the project version in pyproject.toml.

    \b
        rvn python bump patch     # 1.2.3 → 1.2.4
        rvn python bump minor     # 1.2.3 → 1.3.0
        rvn python bump major     # 1.2.3 → 2.0.0
    """
    validate_bump_part(part)

    cwd = directory.resolve()
    pyproject = cwd / "pyproject.toml"
    if not pyproject.exists():
        output.fatal("No pyproject.toml found in the target directory.")

    content = pyproject.read_text()
    m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    if not m:
        output.fatal(
            "Could not find 'version = \"...\"' in pyproject.toml.\n"
            "  Ensure the [project] table has a version field."
        )

    old_version = m.group(1)
    new_version = bump_semver(old_version, part)
    new_content = content[: m.start(1)] + new_version + content[m.end(1) :]
    pyproject.write_text(new_content)
    output.success(f"Bumped version: {old_version} → {new_version}")


# ── index-url ─────────────────────────────────────────────────────────────────


@app.command("index-url")
def python_index_url(
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    with_auth: bool = typer.Option(False, "--auth", help="Include token in URL."),
) -> None:
    """Print the private simple-index URL for use in pip / uv / Poetry."""
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    slug = repo or cfg.registry_defaults("pypi").default_repo
    if not slug:
        output.fatal("No repository configured.")

    url = pypi_reg.simple_index_url(p.api_url, slug)
    if with_auth:
        output.fatal(
            "Refusing to print a credential-bearing URL. "
            "Use `rvn python install` or configure pip/uv with RVN_TOKEN."
        )
    typer.echo(url)
