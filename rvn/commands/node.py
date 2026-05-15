"""rvn node — Node.js ecosystem commands.

Project lifecycle + npm registry commands in one place:

    rvn node sync                       # npm ci / install (or yarn / pnpm)
    rvn node add lodash@4               # npm install --save + package.json
    rvn node add --dev @types/node      # npm install --save-dev
    rvn node remove lodash              # npm uninstall --save
    rvn node pin 20                     # install Node 20 via fnm / volta / nvm
    rvn node install lodash             # install from private registry
    rvn node publish                    # publish to private npm registry
    rvn node registry-url               # print private registry URL
    rvn node npmrc                      # print .npmrc snippet
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import typer

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import manifest as mf
from .. import output
from ..registries import npm as npm_reg
from ..routing import RoutingMode, get_router
from ..runtimes import tools


app = typer.Typer(
    name="node",
    help="Node.js ecosystem — project lifecycle + npm registry.",
    no_args_is_help=True,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _creds(profile: str | None, repo: str | None) -> tuple | None:
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile) or p.token
    slug = repo or cfg.registry_defaults("npm").default_repo
    if not slug or not token:
        return None
    return p.api_url, slug, token


def _detect_pm(cwd: Path) -> str:
    if (cwd / "pnpm-lock.yaml").exists() and tools.resolve("pnpm"):
        return "pnpm"
    if (cwd / "yarn.lock").exists() and tools.resolve("yarn"):
        return "yarn"
    return "npm"


def _inject_npm_env(env: dict, reg_url: str, token: str, pm: str = "npm") -> None:
    host = urlparse(reg_url).netloc
    env[f"NPM_CONFIG_//{host}/:_authToken"] = token
    if pm == "yarn":
        env["YARN_REGISTRY"] = reg_url
        env["YARN_NPM_REGISTRY_SERVER"] = reg_url
        env["YARN_NPM_AUTH_TOKEN"] = token
    elif pm == "pnpm":
        env["npm_config_registry"] = reg_url


# ── sync ──────────────────────────────────────────────────────────────────────


@app.command("sync")
def node_sync(
    frozen: bool = typer.Option(
        True, "--frozen/--no-frozen", help="Use ci / frozen-lockfile (default: on)."
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    no_inject: bool = typer.Option(False, "--no-inject"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
    routing: RoutingMode = typer.Option(
        "canonical",
        "--routing",
        help="URL routing: canonical (default) | unified (not yet implemented).",
    ),
) -> None:
    """Install all Node.js dependencies from package.json.

    Auto-selects npm / yarn / pnpm based on lock-file presence.
    """
    cwd = directory.resolve()
    pm = _detect_pm(cwd)
    env = {**os.environ}

    if not no_inject:
        creds = _creds(profile, repo)
        if creds:
            api_url, slug, token = creds
            try:
                reg_url = get_router(routing).npm_registry_url(api_url, slug)
            except NotImplementedError as exc:
                output.fatal(str(exc))
            _inject_npm_env(env, reg_url, token, pm)
        else:
            output.warn("No registry credentials — syncing from public registry only.")

    if pm == "pnpm":
        cmd = ["pnpm", "install"] + (
            ["--frozen-lockfile"] if frozen and (cwd / "pnpm-lock.yaml").exists() else []
        )
    elif pm == "yarn":
        cmd = ["yarn", "install"] + (["--frozen-lockfile"] if frozen else [])
    else:
        if frozen and (cwd / "package-lock.json").exists():
            cmd = [tools.npm(), "ci"]
        else:
            cmd = [tools.npm(), "install"]

    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)
    output.success("Sync complete.")


# ── add / remove ──────────────────────────────────────────────────────────────


@app.command("add")
def node_add(
    spec: str = typer.Argument(..., help="Package spec, e.g. 'lodash@4' or '@scope/pkg'."),
    dev: bool = typer.Option(False, "--dev", "-D", help="Save as devDependency."),
    no_sync: bool = typer.Option(False, "--no-sync", help="Update package.json only."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
    routing: RoutingMode = typer.Option(
        "canonical",
        "--routing",
        help="URL routing: canonical (default) | unified (not yet implemented).",
    ),
) -> None:
    """Add a Node dependency to package.json and install it."""
    cwd = directory.resolve()
    info = mf.detect(cwd)
    if info is None or info.eco != "node":
        output.fatal("No package.json found.")

    changed = mf.add_dep(info, spec, dev=dev)
    if changed:
        output.success(f"Added '{spec}' to {info.path.name}")
    else:
        output.info(f"'{spec}' already present — version updated if needed.")

    if no_sync:
        return

    env = {**os.environ}
    creds = _creds(profile, repo)
    pm = _detect_pm(cwd)

    if creds:
        api_url, slug, token = creds
        try:
            reg_url = get_router(routing).npm_registry_url(api_url, slug)
        except NotImplementedError as exc:
            output.fatal(str(exc))
        _inject_npm_env(env, reg_url, token, pm)

    flag = "--save-dev" if dev else "--save"
    if pm == "pnpm":
        cmd = ["pnpm", "add"] + (["--save-dev"] if dev else []) + [spec]
    elif pm == "yarn":
        cmd = ["yarn", "add"] + (["--dev"] if dev else []) + [spec]
    else:
        cmd = [tools.npm(), "install", flag, spec]

    if creds and pm == "npm":
        api_url, slug, token = creds
        try:
            cmd.extend(["--registry", get_router(routing).npm_registry_url(api_url, slug)])
        except NotImplementedError as exc:
            output.fatal(str(exc))

    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


@app.command("remove")
def node_remove(
    name: str = typer.Argument(..., help="Package name to remove."),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
) -> None:
    """Remove a Node dependency from package.json."""
    cwd = directory.resolve()
    info = mf.detect(cwd)
    if info is None or info.eco != "node":
        output.fatal("No package.json found.")

    pm = _detect_pm(cwd)
    removed_manifest = mf.remove_dep(info, name)

    # Also run uninstall to keep node_modules and lock file in sync
    if pm == "pnpm":
        cmd = ["pnpm", "remove", name]
    elif pm == "yarn":
        cmd = ["yarn", "remove", name]
    else:
        cmd = [tools.npm(), "uninstall", "--save", name]

    output.info(f"Running: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, cwd=str(cwd), check=True)
        output.success(f"Removed '{name}'.")
    except subprocess.CalledProcessError as exc:
        if removed_manifest:
            output.warn(f"Removed from package.json but {pm} uninstall failed.")
        else:
            output.warn(f"'{name}' not found.")
            raise typer.Exit(1) from exc


# ── pin (runtime version) ─────────────────────────────────────────────────────


@app.command("pin")
def node_pin(
    version: str = typer.Argument(..., help="Node.js version, e.g. 20 or 20.11.0."),
    write_file: bool = typer.Option(
        True, "--write-file/--no-write-file", help="Write .nvmrc / .node-version."
    ),
) -> None:
    """Install a Node.js runtime version and pin it for the project.

    \b
    Uses volta, fnm, or nvm (detected in that order).

        rvn node pin 20
        rvn node pin 20.11.0
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
        # nvm is a shell function — cannot call directly from Python
        output.warn(
            f"No Node version manager found.  "
            f"Install fnm (https://github.com/Schniz/fnm) or volta (https://volta.sh).\n"
            f"If using nvm, run:  nvm install {version}"
        )
        if write_file:
            Path(".nvmrc").write_text(version + "\n")
            output.info(f"Wrote .nvmrc = {version}")
        raise typer.Exit(1)


# ── install (from private registry) ──────────────────────────────────────────


@app.command("install")
def node_install(
    packages: list[str] = typer.Argument(..., help="Packages to install."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    save: bool = typer.Option(False, "--save", help="Save to package.json dependencies."),
    save_dev: bool = typer.Option(False, "--dev", "-D", help="Save to devDependencies."),
    routing: RoutingMode = typer.Option(
        "canonical",
        "--routing",
        help="URL routing: canonical (default) | unified (not yet implemented).",
    ),
) -> None:
    """Install Node packages from the private npm registry."""
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile) or p.token
    slug = repo or cfg.registry_defaults("npm").default_repo
    if not slug:
        output.fatal("No repository configured. Pass --repo or set a default.")
    if not token:
        output.fatal("Not authenticated. Run `rvn login` first.")

    extra_args: list[str] = []
    if save:
        extra_args.append("--save")
    if save_dev:
        extra_args.append("--save-dev")

    try:
        reg_url = get_router(routing).npm_registry_url(p.api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))

    npm_reg.install(
        registry_url=reg_url,
        token=token,
        packages=packages,
        extra_args=extra_args,
    )


# ── publish ───────────────────────────────────────────────────────────────────


@app.command("publish")
def node_publish(
    package_dir: Path = typer.Argument(Path("."), help="Directory with package.json."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option(
        "canonical",
        "--routing",
        help="URL routing: canonical (default) | unified (not yet implemented).",
    ),
) -> None:
    """Publish the npm package to the private registry."""
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile) or p.token
    slug = repo or cfg.registry_defaults("npm").default_repo
    if not slug:
        output.fatal("No repository configured.")
    if not token:
        output.fatal("Not authenticated. Run `rvn login`.")

    try:
        reg_url = get_router(routing).npm_registry_url(p.api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))

    results = npm_reg.publish(
        registry_url=reg_url,
        token=token,
        package_dir=package_dir,
    )
    for result in results:
        if result.ok:
            output.success(f"Published {result.filename} ({result.version})")
        else:
            output.error(f"Publish failed: {result.detail}")
            raise typer.Exit(1)


# ── registry-url / npmrc ──────────────────────────────────────────────────────


@app.command("registry-url")
def node_registry_url(
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Print the private npm registry URL."""
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    slug = repo or cfg.registry_defaults("npm").default_repo
    if not slug:
        output.fatal("No repository configured.")
    typer.echo(npm_reg.registry_url(p.api_url, slug))


@app.command("npmrc")
def node_npmrc(
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Print .npmrc configuration snippet for this registry."""
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile) or p.token
    slug = repo or cfg.registry_defaults("npm").default_repo
    if not slug:
        output.fatal("No repository configured.")

    reg_url = npm_reg.registry_url(p.api_url, slug)
    host = urlparse(reg_url).netloc
    lines = [f"registry={reg_url}"]
    if token:
        lines.append(f"//{host}/:_authToken={token}")
    typer.echo("\n".join(lines))


# ── yank ──────────────────────────────────────────────────────────────────────


@app.command("yank")
def node_yank(
    package: str = typer.Argument(..., help="Package name."),
    version: str = typer.Argument(..., help="Version."),
) -> None:
    """[Not supported] The npm protocol does not support yanking.

    Use `rvn node deprecate` to mark a version as deprecated and warn
    installers away from it.
    """
    output.error(
        "The npm registry protocol does not support yanking.\n"
        '  Use `rvn node deprecate <package>@<version> "<message>"` instead.'
    )
    raise typer.Exit(1)


# ── deprecate ─────────────────────────────────────────────────────────────────


@app.command("deprecate")
def node_deprecate(
    spec: str = typer.Argument(..., help="Package spec: name@version or name@range."),
    message: str = typer.Argument(..., help="Deprecation message shown to installers."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Deprecate a package version in the private npm registry.

    \b
        rvn node deprecate my-pkg@1.2.3 "use my-pkg@2 instead"
        rvn node deprecate "my-pkg@<2.0.0" "1.x is end-of-life"
    """
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile) or p.token
    slug = repo or cfg.registry_defaults("npm").default_repo
    if not slug:
        output.fatal("No repository configured. Pass --repo or set a default.")
    if not token:
        output.fatal("Not authenticated. Run `rvn login` first.")

    reg_url = npm_reg.registry_url(p.api_url, slug)
    env = {**os.environ}
    _inject_npm_env(env, reg_url, token)
    cmd = ["npm", "deprecate", spec, message, "--registry", reg_url]
    output.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env, check=False)
    if result.returncode != 0:
        output.fatal(f"npm deprecate failed (exit {result.returncode}).")
    output.success(f"Deprecated {spec}.")


# ── bump ──────────────────────────────────────────────────────────────────────


@app.command("bump")
def node_bump(
    part: str = typer.Argument(..., help="Version part to bump: major | minor | patch."),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
    no_git_tag: bool = typer.Option(
        False, "--no-git-tag", help="Skip the git tag created by npm version."
    ),
) -> None:
    """Bump the package.json version (delegates to npm version).

    \b
        rvn node bump patch           # 1.2.3 → 1.2.4
        rvn node bump minor           # 1.2.3 → 1.3.0
        rvn node bump major           # 1.2.3 → 2.0.0
        rvn node bump patch --no-git-tag
    """
    _valid = {"major", "minor", "patch"}
    if part not in _valid:
        output.fatal(f"Invalid part '{part}'. Must be one of: {', '.join(sorted(_valid))}")

    cwd = directory.resolve()
    cmd = [tools.npm(), "version", part]
    if no_git_tag:
        cmd.append("--no-git-tag-version")
    output.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        output.fatal(result.stderr.strip() or f"npm version failed (exit {result.returncode}).")
    output.success(f"Bumped to {result.stdout.strip()}.")
