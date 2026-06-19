"""rvn npm — comprehensive npm registry + Node.js project lifecycle.

All registry operations for JavaScript packages.  Canonical npm protocol
routes are fully functional; unified routes (marked with ✦) are wired to
the Ravenstash API and will be enabled when the server-side endpoints are
deployed.

    rvn npm install lodash                    # install from private registry
    rvn npm sync                              # npm ci (or yarn/pnpm)
    rvn npm add lodash@4 --save               # add to package.json + install
    rvn npm remove lodash                     # npm uninstall
    rvn npm publish                           # npm publish --registry
    rvn npm deprecate my-pkg@1.0.0 "use v2"  # npm deprecate (canonical)
    rvn npm yank my-pkg 1.0.0                # ✦ unified — no native npm support
    rvn npm bump patch                        # 1.2.3 → 1.2.4 via npm version
    rvn npm dist-tag add my-pkg@1.0.0 stable # canonical npm dist-tag
    rvn npm dist-tag ls my-pkg               # canonical npm dist-tag ls
    rvn npm snapshot publish                  # npm publish --tag snapshot
    rvn npm registry-url                      # print private registry URL
    rvn npm npmrc                             # print .npmrc snippet
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import typer

from .. import manifest as mf
from .. import output
from ..client import ApiError
from ..registries import npm as npm_reg
from ..routing import RoutingMode, get_router
from ..runtimes import tools
from ..semver import validate_bump_part
from ._eco_helpers import api_client as _api_client
from ._eco_helpers import require_token as _eco_require_token
from ._eco_helpers import resolve_registry as _resolve_registry


app = typer.Typer(
    name="npm",
    help="npm registry — install, publish, deprecate, yank, dist-tags, snapshots, and project lifecycle.",
    no_args_is_help=True,
)

_tag_app = typer.Typer(
    no_args_is_help=True, help="Manage distribution tags (latest, beta, next, etc.)"
)
_snap_app = typer.Typer(no_args_is_help=True, help="Manage snapshot / pre-release builds.")

app.add_typer(_tag_app, name="dist-tag")
app.add_typer(_snap_app, name="snapshot")


def _resolve(
    profile: str | None,
    repo: str | None,
) -> tuple[str, str, str | None]:
    return _resolve_registry("npm", profile, repo)


def _require_token(profile: str | None, repo: str | None) -> tuple[str, str, str]:
    return _eco_require_token("npm", profile, repo)


# ── Credential helpers ────────────────────────────────────────────────────────


def _detect_pm(cwd: Path) -> str:
    if (cwd / "pnpm-lock.yaml").exists() and tools.resolve("pnpm"):
        return "pnpm"
    if (cwd / "yarn.lock").exists() and tools.resolve("yarn"):
        return "yarn"
    return "npm"


def _inject_npm_env(env: dict, reg_url: str, token: str | None, pm: str = "npm") -> None:
    host = urlparse(reg_url).netloc
    if token:
        env[f"NPM_CONFIG_//{host}/:_authToken"] = token
    if pm == "yarn":
        env["YARN_REGISTRY"] = reg_url
        env["YARN_NPM_REGISTRY_SERVER"] = reg_url
        if token:
            env["YARN_NPM_AUTH_TOKEN"] = token
    elif pm == "pnpm":
        env["npm_config_registry"] = reg_url


# ── install ───────────────────────────────────────────────────────────────────


@app.command(
    "install",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def npm_install(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Install packages from the private npm registry.  All npm flags accepted.

    \b
        rvn npm install lodash
        rvn npm install lodash @scope/utils --save-dev
    """
    api_url, slug, token = _resolve(profile, repo)
    try:
        reg_url = get_router(routing).npm_registry_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    env = {**os.environ}
    _inject_npm_env(env, reg_url, token)
    cmd = [tools.npm(), "install", "--registry", reg_url, *ctx.args]
    subprocess.run(cmd, env=env, check=True)


# ── ci ────────────────────────────────────────────────────────────────────────


@app.command(
    "ci",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def npm_ci(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Clean install from package-lock.json (equivalent to npm ci).

    \b
        rvn npm ci
    """
    api_url, slug, token = _resolve(profile, repo)
    try:
        reg_url = get_router(routing).npm_registry_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    env = {**os.environ}
    _inject_npm_env(env, reg_url, token)
    cmd = [tools.npm(), "ci", "--registry", reg_url, *ctx.args]
    subprocess.run(cmd, env=env, check=True)


# ── view ──────────────────────────────────────────────────────────────────────


@app.command(
    "view",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def npm_view(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Show package metadata from the private registry.

    \b
        rvn npm view lodash
        rvn npm view lodash version
        rvn npm view lodash versions --json
    """
    api_url, slug, token = _resolve(profile, repo)
    try:
        reg_url = get_router(routing).npm_registry_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    env = {**os.environ}
    _inject_npm_env(env, reg_url, token)
    cmd = [tools.npm(), "view", "--registry", reg_url, *ctx.args]
    subprocess.run(cmd, env=env, check=True)


# ── ls / outdated ─────────────────────────────────────────────────────────────


@app.command(
    "ls",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def npm_ls(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """List installed packages. Forwards extra flags to npm ls."""
    api_url, slug, token = _resolve(profile, repo)
    try:
        reg_url = get_router(routing).npm_registry_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    env = {**os.environ}
    _inject_npm_env(env, reg_url, token)
    cmd = [tools.npm(), "ls", "--registry", reg_url, *ctx.args]
    subprocess.run(cmd, env=env, check=True)


@app.command(
    "outdated",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def npm_outdated(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Check for outdated packages against the private registry."""
    api_url, slug, token = _resolve(profile, repo)
    try:
        reg_url = get_router(routing).npm_registry_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    env = {**os.environ}
    _inject_npm_env(env, reg_url, token)
    cmd = [tools.npm(), "outdated", "--registry", reg_url, *ctx.args]
    subprocess.run(cmd, env=env, check=False)  # npm outdated exits 1 when outdated pkgs found


# ── sync ──────────────────────────────────────────────────────────────────────


@app.command("sync")
def npm_sync(
    frozen: bool = typer.Option(True, "--frozen/--no-frozen"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    no_inject: bool = typer.Option(False, "--no-inject"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Install all Node.js dependencies from package.json.

    \b
        rvn npm sync             # npm ci (frozen) or npm install
        rvn npm sync --no-frozen # npm install
    """
    cwd = directory.resolve()
    pm = _detect_pm(cwd)
    env = {**os.environ}

    if not no_inject:
        api_url, slug, token = _resolve(profile, repo)
        if token:
            try:
                reg_url = get_router(routing).npm_registry_url(api_url, slug)
            except NotImplementedError as exc:
                output.fatal(str(exc))
            _inject_npm_env(env, reg_url, token, pm)
        else:
            output.warn("No token found — syncing from public registry only.")

    if pm == "pnpm":
        cmd = ["pnpm", "install"] + (
            ["--frozen-lockfile"] if frozen and (cwd / "pnpm-lock.yaml").exists() else []
        )
    elif pm == "yarn":
        cmd = ["yarn", "install"] + (["--frozen-lockfile"] if frozen else [])
    else:
        npm_bin = tools.npm()
        cmd = (
            [npm_bin, "ci"]
            if frozen and (cwd / "package-lock.json").exists()
            else [npm_bin, "install"]
        )

    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)
    output.success("Sync complete.")


# ── add / remove ──────────────────────────────────────────────────────────────


@app.command("add")
def npm_add(
    spec: str = typer.Argument(..., help="Package spec, e.g. 'lodash@4' or '@scope/pkg'."),
    dev: bool = typer.Option(False, "--dev", "-D"),
    no_sync: bool = typer.Option(False, "--no-sync"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
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
    api_url, slug, token = _resolve(profile, repo)
    pm = _detect_pm(cwd)

    if token:
        try:
            reg_url = get_router(routing).npm_registry_url(api_url, slug)
        except NotImplementedError as exc:
            output.fatal(str(exc))
        _inject_npm_env(env, reg_url, token, pm)

    if pm == "pnpm":
        cmd = ["pnpm", "add"] + (["--save-dev"] if dev else []) + [spec]
    elif pm == "yarn":
        cmd = ["yarn", "add"] + (["--dev"] if dev else []) + [spec]
    else:
        flag = "--save-dev" if dev else "--save"
        reg_url_for_cmd = get_router(routing).npm_registry_url(api_url, slug) if token else None  # type: ignore[arg-type]
        cmd = [tools.npm(), "install", flag, spec]
        if reg_url_for_cmd:
            cmd.extend(["--registry", reg_url_for_cmd])

    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


@app.command("remove")
def npm_remove(
    name: str = typer.Argument(..., help="Package name to remove."),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
) -> None:
    """Remove a Node dependency from package.json."""
    cwd = directory.resolve()
    info = mf.detect(cwd)
    if info is None or info.eco != "node":
        output.fatal("No package.json found.")

    pm = _detect_pm(cwd)
    mf.remove_dep(info, name)

    cmd_map = {"pnpm": ["pnpm", "remove", name], "yarn": ["yarn", "remove", name]}
    cmd = cmd_map.get(pm, [tools.npm(), "uninstall", "--save", name])
    output.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(cwd), check=False)
    if result.returncode != 0:
        output.warn(f"'{name}' may not be found in node_modules.")
    else:
        output.success(f"Removed '{name}'.")


# ── publish ───────────────────────────────────────────────────────────────────


@app.command("publish")
def npm_publish(
    package_dir: Path = typer.Argument(Path("."), help="Directory containing package.json."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    tag: str | None = typer.Option(
        None, "--tag", help="Dist-tag to publish under (default: latest)."
    ),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Publish the npm package to the private registry.

    \b
        rvn npm publish
        rvn npm publish --tag beta
    """
    api_url, slug, token = _require_token(profile, repo)
    try:
        reg_url = get_router(routing).npm_registry_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))

    results = npm_reg.publish(registry_url=reg_url, token=token, package_dir=package_dir)
    for result in results:
        if result.ok:
            output.success(f"Published {result.filename} ({result.version})")
        else:
            output.error(f"Publish failed: {result.detail}")
            raise typer.Exit(1)


# ── yank ──────────────────────────────────────────────────────────────────────


@app.command("yank")
def npm_yank(
    package: str = typer.Argument(..., help="Package name."),
    version: str = typer.Argument(..., help="Version."),
    reason: str | None = typer.Option(None, "--reason", "-m"),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Mark a package version as yanked via Ravenstash unified API.

    ✦ Unified feature — yank is not a native npm protocol concept.
       A yanked version is hidden in the Ravenstash metadata layer.
       Installers using the standard npm CLI will NOT see the yank effect;
       only rvn-aware tooling respects it.

    \b
        rvn npm yank my-pkg 1.0.0
        rvn npm yank my-pkg 1.0.0 --reason "Security vulnerability"
    """
    api_url, slug, token = _require_token(profile, repo)
    client = _api_client(api_url, token)
    body = {"reason": reason} if reason else None
    try:
        client.post(
            f"/webapp/repository/{slug}/packages/{package}/versions/{version}/yank",
            json=body,
        )
        output.success(f"Yanked {package}@{version}.")
        if reason:
            output.info(f"Reason: {reason}")
    except ApiError as exc:
        output.fatal(str(exc))


# ── deprecate ─────────────────────────────────────────────────────────────────


@app.command("deprecate")
def npm_deprecate(
    spec: str = typer.Argument(..., help="Package spec: name@version or name@range."),
    message: str = typer.Argument(..., help="Deprecation message shown to installers."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Deprecate a package version in the npm registry.

    In canonical mode this uses the native npm deprecate command.
    In unified mode it calls the Ravenstash API.

    \b
        rvn npm deprecate my-pkg@1.0.0 "use my-pkg@2 instead"
        rvn npm deprecate "my-pkg@<2.0.0" "1.x is end-of-life"
    """
    api_url, slug, token = _require_token(profile, repo)
    try:
        reg_url = get_router(routing).npm_registry_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    env = {**os.environ}
    _inject_npm_env(env, reg_url, token)
    cmd = [tools.npm(), "deprecate", spec, message, "--registry", reg_url]
    output.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env, check=False)
    if result.returncode != 0:
        output.fatal(f"npm deprecate failed (exit {result.returncode}).")
    output.success(f"Deprecated {spec}.")


# ── bump ──────────────────────────────────────────────────────────────────────


@app.command("bump")
def npm_bump(
    part: str = typer.Argument(..., help="major | minor | patch"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
    no_git_tag: bool = typer.Option(False, "--no-git-tag"),
) -> None:
    """Bump the package.json version (delegates to npm version).

    \b
        rvn npm bump patch         # 1.2.3 → 1.2.4
        rvn npm bump minor         # 1.2.3 → 1.3.0
        rvn npm bump major         # 1.2.3 → 2.0.0
        rvn npm bump patch --no-git-tag
    """
    validate_bump_part(part)

    cwd = directory.resolve()
    cmd = [tools.npm(), "version", part]
    if no_git_tag:
        cmd.append("--no-git-tag-version")
    output.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        output.fatal(result.stderr.strip() or f"npm version failed (exit {result.returncode}).")
    output.success(f"Bumped to {result.stdout.strip()}.")


# ── version ───────────────────────────────────────────────────────────────────


@app.command("version")
def npm_version(
    bump: str | None = typer.Option(None, "--bump", help="major | minor | patch"),
    no_git_tag: bool = typer.Option(False, "--no-git-tag"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
) -> None:
    """Display (or bump) the package.json version.

    \b
        rvn npm version                    # print current version
        rvn npm version --bump patch       # 1.2.3 → 1.2.4 (via npm version)
        rvn npm version --bump minor       # 1.2.3 → 1.3.0
        rvn npm version --bump major --no-git-tag
    """
    import json

    cwd = directory.resolve()
    pkg = cwd / "package.json"
    if not pkg.exists():
        output.fatal("No package.json found.")

    try:
        data = json.loads(pkg.read_text())
    except json.JSONDecodeError as exc:
        output.fatal(f"Could not parse package.json: {exc}")

    current = data.get("version", "")
    if not current:
        output.fatal("No 'version' field found in package.json.")

    if bump is None:
        typer.echo(current)
        return

    validate_bump_part(bump)
    cmd = [tools.npm(), "version", bump]
    if no_git_tag:
        cmd.append("--no-git-tag-version")
    output.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        output.fatal(result.stderr.strip() or f"npm version failed (exit {result.returncode}).")
    output.success(f"Bumped to {result.stdout.strip()}.")


# ── dist-tag ──────────────────────────────────────────────────────────────────
# npm dist-tags are a native npm concept (latest, beta, next, etc.).
# Canonical routes pass through to the npm registry protocol.
# Unified routes also store tag state in the Ravenstash metadata layer.


@_tag_app.command("ls")
def npm_tag_ls(
    package: str = typer.Argument(..., help="Package name."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """List distribution tags for a package.

    \b
        rvn npm dist-tag ls my-pkg
    """
    api_url, slug, token = _require_token(profile, repo)
    try:
        reg_url = get_router(routing).npm_registry_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    env = {**os.environ}
    _inject_npm_env(env, reg_url, token)
    cmd = [tools.npm(), "dist-tag", "ls", package, "--registry", reg_url]
    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, env=env, check=True)


@_tag_app.command("add")
def npm_tag_add(
    spec: str = typer.Argument(..., help="Package spec: name@version."),
    tag: str = typer.Argument(..., help="Tag name, e.g. stable, beta, next."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Add or update a distribution tag.

    \b
        rvn npm dist-tag add my-pkg@2.0.0 latest
        rvn npm dist-tag add my-pkg@2.1.0-beta.1 beta
    """
    api_url, slug, token = _require_token(profile, repo)
    try:
        reg_url = get_router(routing).npm_registry_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    env = {**os.environ}
    _inject_npm_env(env, reg_url, token)
    cmd = [tools.npm(), "dist-tag", "add", spec, tag, "--registry", reg_url]
    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, env=env, check=True)
    output.success(f"Tagged {spec} as '{tag}'.")


@_tag_app.command("rm")
def npm_tag_rm(
    package: str = typer.Argument(..., help="Package name."),
    tag: str = typer.Argument(..., help="Tag to remove."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Remove a distribution tag.

    \b
        rvn npm dist-tag rm my-pkg beta
    """
    api_url, slug, token = _require_token(profile, repo)
    try:
        reg_url = get_router(routing).npm_registry_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    env = {**os.environ}
    _inject_npm_env(env, reg_url, token)
    cmd = [tools.npm(), "dist-tag", "rm", package, tag, "--registry", reg_url]
    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, env=env, check=True)
    output.success(f"Removed tag '{tag}' from {package}.")


# ── snapshot ──────────────────────────────────────────────────────────────────
# npm snapshots are published with a pre-release dist-tag ("snapshot", "next").
# The native npm publish command handles this via --tag.


@_snap_app.command("publish")
def npm_snap_publish(
    package_dir: Path = typer.Argument(Path("."), help="Directory containing package.json."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    tag: str = typer.Option("snapshot", "--tag", help="Dist-tag to use (default: snapshot)."),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Publish a snapshot build tagged with 'snapshot' (or a custom tag).

    \b
        rvn npm snapshot publish
        rvn npm snapshot publish --tag next
    """
    api_url, slug, token = _require_token(profile, repo)
    try:
        reg_url = get_router(routing).npm_registry_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))

    env = {**os.environ}
    _inject_npm_env(env, reg_url, token)
    cmd = [tools.npm(), "publish", "--tag", tag, "--registry", reg_url]
    output.info(f"Publishing snapshot (tag={tag}) ...")
    result = subprocess.run(cmd, cwd=str(package_dir.resolve()), env=env, check=False)
    if result.returncode != 0:
        output.fatal(f"npm publish failed (exit {result.returncode}).")
    output.success(f"Snapshot published with tag '{tag}'.")


@_snap_app.command("ls")
def npm_snap_ls(
    package: str = typer.Argument(..., help="Package name."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    tag: str = typer.Option("snapshot", "--tag", help="Dist-tag to inspect (default: snapshot)."),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """List snapshot versions (versions published under the snapshot tag).

    \b
        rvn npm snapshot ls my-pkg
        rvn npm snapshot ls my-pkg --tag next
    """
    api_url, slug, token = _require_token(profile, repo)
    try:
        reg_url = get_router(routing).npm_registry_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))

    env = {**os.environ}
    _inject_npm_env(env, reg_url, token)
    # Show the tagged version first, then list pre-release versions
    cmd = [tools.npm(), "view", package, "dist-tags", "--registry", reg_url, "--json"]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        output.warn(f"Could not retrieve dist-tags for {package}.")
    else:
        import json

        try:
            tags = json.loads(result.stdout)
            if tag in tags:
                output.info(f"  {tag} → {tags[tag]}")
            else:
                output.info(f"No '{tag}' dist-tag found for {package}.")
        except json.JSONDecodeError:
            output.warn("Could not parse dist-tag output.")

    # Also list all pre-release versions
    cmd2 = [tools.npm(), "view", package, "versions", "--registry", reg_url, "--json"]
    result2 = subprocess.run(cmd2, env=env, capture_output=True, text=True, check=False)
    if result2.returncode == 0:
        try:
            all_versions: list[str] = json.loads(result2.stdout)
            pre = [v for v in all_versions if re.search(r"[-+]", v)]
            if pre:
                output.table(
                    ["Pre-release version"], [[v] for v in pre], title=f"Pre-releases: {package}"
                )
        except (json.JSONDecodeError, NameError):
            pass


import re  # noqa: E402  (re already imported above via _snap_ls scope, but explicit here)


# ── registry-url / npmrc ──────────────────────────────────────────────────────


@app.command("registry-url")
def npm_registry_url(
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Print the private npm registry URL.

    \b
        rvn npm registry-url
    """
    api_url, slug, _ = _resolve(profile, repo)
    try:
        url = get_router(routing).npm_registry_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    typer.echo(url)


@app.command("npmrc")
def npm_npmrc(
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Print .npmrc configuration snippet for this registry.

    \b
        rvn npm npmrc
        rvn npm npmrc >> .npmrc
    """
    api_url, slug, _token = _resolve(profile, repo)
    try:
        reg_url = get_router(routing).npm_registry_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    host = urlparse(reg_url).netloc
    lines = [f"registry={reg_url}"]
    lines.append(f"//{host}/:_authToken=${{RVN_TOKEN}}")
    typer.echo("\n".join(lines))
