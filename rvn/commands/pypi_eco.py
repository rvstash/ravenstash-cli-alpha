"""rvn pypi — comprehensive PyPI registry + Python project lifecycle.

All registry operations for Python packages, from first install to release
management.  Canonical routes are fully functional; unified routes (marked
with ✦) are wired to the RavenStash API and will be enabled as soon as the
server-side endpoints are deployed.

    rvn pypi install requests boto3           # install from private index
    rvn pypi sync                             # uv sync / pip install -r
    rvn pypi add requests>=2.28               # update pyproject.toml + install
    rvn pypi remove requests                  # remove from pyproject.toml
    rvn pypi publish dist/                    # upload wheel/sdist
    rvn pypi yank my-pkg 1.2.3               # mark version yanked (✦ unified)
    rvn pypi bump patch                       # 1.2.3 → 1.2.4 in pyproject.toml
    rvn pypi dist-tag add my-pkg@1.0.0 stable # ✦ unified
    rvn pypi dist-tag ls my-pkg              # ✦ unified
    rvn pypi snapshot publish dist/          # publish pre-release (devN)
    rvn pypi index-url                        # print private index URL
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import typer

from .. import manifest as mf
from .. import output
from ..client import ApiError
from ..registries import pypi as pypi_reg
from ..routing import RoutingMode, get_router
from ..runtimes import tools
from ..semver import bump_semver, validate_bump_part
from ._eco_helpers import api_client as _api_client
from ._eco_helpers import require_token as _eco_require_token
from ._eco_helpers import resolve_registry as _resolve_registry


app = typer.Typer(
    name="pypi",
    help="PyPI registry — install, publish, yank, dist-tags, snapshots, and project lifecycle.",
    no_args_is_help=True,
)

# Sub-typers for grouped commands
_tag_app = typer.Typer(no_args_is_help=True, help="Manage distribution tags (release, beta, etc.)")
_snap_app = typer.Typer(no_args_is_help=True, help="Manage snapshot / pre-release builds.")

app.add_typer(_tag_app, name="dist-tag")
app.add_typer(_snap_app, name="snapshot")


def _resolve(
    profile: str | None,
    repo: str | None,
) -> tuple[str, str, str | None]:
    return _resolve_registry("pypi", profile, repo)


def _require_token(profile: str | None, repo: str | None) -> tuple[str, str, str]:
    return _eco_require_token("pypi", profile, repo)


# ── Credential helpers ────────────────────────────────────────────────────────


def _authed_index(base_url: str, token: str) -> str:
    parsed = urlparse(base_url)
    return urlunparse(parsed._replace(netloc=f"__token__:{token}@{parsed.netloc}"))


def _env_with_index(base_url: str, token: str | None) -> dict:
    env = {**os.environ}
    if token:
        authed = _authed_index(base_url, token)
        existing = env.get("UV_EXTRA_INDEX_URL", "")
        env["UV_EXTRA_INDEX_URL"] = (existing + " " + authed).strip()
        env["PIP_EXTRA_INDEX_URL"] = authed
    return env


def _pip_cmd() -> list[str]:
    return tools.pip_cmd()


# ── install ───────────────────────────────────────────────────────────────────


@app.command(
    "install",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def pypi_install(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Install packages from the private index.  All pip/uv-pip flags accepted.

    \b
        rvn pypi install requests boto3
        rvn pypi install -r requirements.txt
        rvn pypi install requests>=2.28 --no-deps
    """
    api_url, slug, token = _resolve(profile, repo)
    try:
        index_url = get_router(routing).pypi_index_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    env = _env_with_index(index_url, token)
    cmd = [
        *_pip_cmd(),
        "install",
        "--extra-index-url",
        _authed_index(index_url, token) if token else index_url,
        *ctx.args,
    ]
    output.info(f"Index: {index_url}")
    subprocess.run(cmd, env=env, check=True)


@app.command(
    "download",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def pypi_download(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    dest: Path = typer.Option(Path("./wheels"), "--dest", "-d"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Download wheels/sdists from the private index without installing.

    \b
        rvn pypi download requests --dest ./wheels
    """
    api_url, slug, token = _resolve(profile, repo)
    try:
        index_url = get_router(routing).pypi_index_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    dest.mkdir(parents=True, exist_ok=True)
    authed = _authed_index(index_url, token) if token else index_url
    cmd = [*_pip_cmd(), "download", "--extra-index-url", authed, "-d", str(dest), *ctx.args]
    output.info(f"Downloading to {dest} ...")
    subprocess.run(cmd, check=True)


@app.command(
    "show",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def pypi_show(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show installed package metadata (pip show). Forwards all pip flags."""
    api_url, slug, token = _resolve(profile, repo)
    index_url = pypi_reg.simple_index_url(api_url, slug)
    env = _env_with_index(index_url, token)
    cmd = [*_pip_cmd(), "show", *ctx.args]
    subprocess.run(cmd, env=env, check=True)


@app.command(
    "list",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def pypi_list(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """List installed packages.  --outdated checks against the private index."""
    api_url, slug, token = _resolve(profile, repo)
    index_url = pypi_reg.simple_index_url(api_url, slug)
    env = _env_with_index(index_url, token)
    cmd = [*_pip_cmd(), "list", *ctx.args]
    subprocess.run(cmd, env=env, check=True)


@app.command(
    "freeze",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def pypi_freeze(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Print installed packages in requirements format."""
    api_url, slug, token = _resolve(profile, repo)
    index_url = pypi_reg.simple_index_url(api_url, slug)
    env = _env_with_index(index_url, token)
    cmd = [*_pip_cmd(), "freeze", *ctx.args]
    subprocess.run(cmd, env=env, check=True)


# ── sync ──────────────────────────────────────────────────────────────────────


@app.command("sync")
def pypi_sync(
    frozen: bool = typer.Option(True, "--frozen/--no-frozen"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    no_inject: bool = typer.Option(False, "--no-inject"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Sync Python dependencies from pyproject.toml or requirements.txt.

    \b
        rvn pypi sync           # uv sync --frozen
        rvn pypi sync --no-frozen
    """
    cwd = directory.resolve()
    env = {**os.environ}

    if not no_inject:
        api_url, slug, token = _resolve(profile, repo)
        if token:
            try:
                base_url = get_router(routing).pypi_index_url(api_url, slug)
            except NotImplementedError as exc:
                output.fatal(str(exc))
            env = _env_with_index(base_url, token)
        else:
            output.warn("No token found — syncing from public index only.")

    info = mf.detect(cwd)
    if info is None or info.eco != "python":
        output.fatal("No Python manifest found (pyproject.toml or requirements.txt).")

    if info.kind == "pyproject":
        uv_path = tools.resolve("uv")
        cmd = (
            ([uv_path, "sync"] + (["--frozen"] if frozen else []))
            if uv_path
            else [*tools.pip_cmd(), "install", "-e", "."]
        )
    else:
        req = str(info.path)
        uv_path = tools.resolve("uv")
        cmd = (
            ([uv_path, "pip", "install", "-r", req])
            if uv_path
            else [*tools.pip_cmd(), "install", "-r", req]
        )

    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)
    output.success("Sync complete.")


# ── add / remove ──────────────────────────────────────────────────────────────


@app.command("add")
def pypi_add(
    spec: str = typer.Argument(..., help="Package spec, e.g. 'requests>=2.28'."),
    dev: bool = typer.Option(False, "--dev", "-D"),
    no_sync: bool = typer.Option(False, "--no-sync"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
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
    api_url, slug, token = _resolve(profile, repo)
    if token:
        try:
            base_url = get_router(routing).pypi_index_url(api_url, slug)
        except NotImplementedError as exc:
            output.fatal(str(exc))
        env = _env_with_index(base_url, token)

    uv_path = tools.resolve("uv")
    cmd = [uv_path, "add", spec] if uv_path else [*tools.pip_cmd(), "install", spec]
    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


@app.command("remove")
def pypi_remove(
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
        output.info("Run `rvn pypi sync` to update your environment.")
    else:
        output.warn(f"'{name}' not found in {info.path.name}")
        raise typer.Exit(1)


# ── publish ───────────────────────────────────────────────────────────────────


@app.command("publish")
def pypi_publish(
    dist_dir: Path = typer.Argument(Path("dist"), help="Directory with wheel/sdist files."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Upload wheel / sdist files to the private PyPI repository.

    \b
        rvn pypi publish              # publishes dist/*.whl + dist/*.tar.gz
        rvn pypi publish dist/        # explicit directory
    """
    api_url, slug, token = _require_token(profile, repo)
    files = list(dist_dir.glob("*.whl")) + list(dist_dir.glob("*.tar.gz"))
    if not files:
        output.fatal(f"No .whl or .tar.gz files found in {dist_dir}")

    try:
        upload_url = get_router(routing).pypi_upload_url(api_url, slug)
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


# ── yank ──────────────────────────────────────────────────────────────────────


@app.command("yank")
def pypi_yank(
    package: str = typer.Argument(..., help="Package name."),
    version: str = typer.Argument(..., help="Version to yank."),
    reason: str | None = typer.Option(
        None, "--reason", "-m", help="Yank reason (shown to installers)."
    ),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Mark a package version as yanked (PEP 592).

    Yanked versions are hidden from resolvers but can still be installed
    when pinned exactly.

    \b
        rvn pypi yank my-pkg 1.2.3
        rvn pypi yank my-pkg 1.2.3 --reason "Contains a critical bug"
    """
    api_url, slug, token = _require_token(profile, repo)
    client = _api_client(api_url, token)
    body = {"reason": reason} if reason else None
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
def pypi_deprecate(
    package: str = typer.Argument(..., help="Package name."),
    version: str = typer.Argument(..., help="Version."),
    message: str = typer.Argument(..., help="Deprecation message."),
) -> None:
    """[Not supported] The PyPI protocol does not support deprecation.

    Use `rvn pypi yank <package> <version>` to hide a version from resolvers.
    """
    output.error(
        "The PyPI protocol does not support package deprecation.\n"
        "  Use `rvn pypi yank <package> <version>` to hide a version from resolvers."
    )
    raise typer.Exit(1)


# ── bump ──────────────────────────────────────────────────────────────────────


@app.command("bump")
def pypi_bump(
    part: str = typer.Argument(..., help="major | minor | patch"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
) -> None:
    """Bump the project version in pyproject.toml.

    \b
        rvn pypi bump patch     # 1.2.3 → 1.2.4
        rvn pypi bump minor     # 1.2.3 → 1.3.0
        rvn pypi bump major     # 1.2.3 → 2.0.0
    """
    validate_bump_part(part)

    pyproject = directory.resolve() / "pyproject.toml"
    if not pyproject.exists():
        output.fatal("No pyproject.toml found.")

    content = pyproject.read_text()
    m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    if not m:
        output.fatal('Could not find version = "..." in [project] table of pyproject.toml.')

    old_ver = m.group(1)
    new_ver = bump_semver(old_ver, part)
    pyproject.write_text(content[: m.start(1)] + new_ver + content[m.end(1) :])
    output.success(f"Bumped version: {old_ver} → {new_ver}")


# ── version ───────────────────────────────────────────────────────────────────


@app.command("version")
def pypi_version(
    bump: str | None = typer.Option(None, "--bump", help="major | minor | patch"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
) -> None:
    """Display (or bump) the project version in pyproject.toml.

    \b
        rvn pypi version                   # print current version
        rvn pypi version --bump patch      # 1.2.3 → 1.2.4
        rvn pypi version --bump minor      # 1.2.3 → 1.3.0
        rvn pypi version --bump major      # 1.2.3 → 2.0.0
    """
    pyproject = directory.resolve() / "pyproject.toml"
    if not pyproject.exists():
        output.fatal("No pyproject.toml found.")

    content = pyproject.read_text()
    m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    if not m:
        output.fatal('Could not find version = "..." in [project] table of pyproject.toml.')

    current = m.group(1)

    if bump is None:
        typer.echo(current)
        return

    validate_bump_part(bump)
    new_ver = bump_semver(current, bump)
    pyproject.write_text(content[: m.start(1)] + new_ver + content[m.end(1) :])
    output.success(f"Bumped version: {current} → {new_ver}")


# ── dist-tag ──────────────────────────────────────────────────────────────────
# Managed via RavenStash unified API.  The PyPI protocol has no native dist-tag
# concept; these tags live in the RavenStash metadata layer and are used by
# rvn (and future rvn-aware tooling) to resolve aliases like "stable" or "beta".


@_tag_app.command("ls")
def pypi_tag_ls(
    package: str = typer.Argument(..., help="Package name."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """List distribution tags for a package.

    \b
        rvn pypi dist-tag ls my-pkg
    """
    api_url, slug, token = _require_token(profile, repo)
    client = _api_client(api_url, token)
    try:
        data = client.get(f"/webapp/repository/{slug}/packages/{package}/dist-tags/").json()
    except ApiError as exc:
        if exc.status_code == 404:
            output.info(f"No dist-tags found for {package} (or feature not yet enabled on server).")
            return
        output.fatal(str(exc))

    tags: dict = data if isinstance(data, dict) else {}
    if not tags:
        output.info(f"No dist-tags for {package!r}.")
        return
    output.table(
        ["Tag", "Version"], [[k, v] for k, v in tags.items()], title=f"Dist-tags: {package}"
    )


@_tag_app.command("add")
def pypi_tag_add(
    spec: str = typer.Argument(..., help="Package spec: name@version, e.g. my-pkg@1.2.3."),
    tag: str = typer.Argument(..., help="Tag name, e.g. stable, beta, latest."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Add or update a distribution tag.

    \b
        rvn pypi dist-tag add my-pkg@1.2.3 stable
        rvn pypi dist-tag add my-pkg@2.0.0-beta.1 beta
    """
    if "@" not in spec:
        output.fatal("Spec must be name@version, e.g. my-pkg@1.2.3")
    name, version = spec.rsplit("@", 1)
    api_url, slug, token = _require_token(profile, repo)
    client = _api_client(api_url, token)
    try:
        client.post(
            f"/webapp/repository/{slug}/packages/{name}/dist-tags/{tag}",
            json={"version": version},
        )
        output.success(f"Tagged {name}@{version} as '{tag}'.")
    except ApiError as exc:
        if exc.status_code == 404:
            output.fatal(
                "dist-tag management requires a newer RavenStash server.\n"
                "  Check for server updates at https://ravenstash.com/changelog"
            )
        output.fatal(str(exc))


@_tag_app.command("rm")
def pypi_tag_rm(
    package: str = typer.Argument(..., help="Package name."),
    tag: str = typer.Argument(..., help="Tag to remove."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Remove a distribution tag.

    \b
        rvn pypi dist-tag rm my-pkg stable
    """
    api_url, slug, token = _require_token(profile, repo)
    client = _api_client(api_url, token)
    try:
        client.delete(f"/webapp/repository/{slug}/packages/{package}/dist-tags/{tag}")
        output.success(f"Removed tag '{tag}' from {package}.")
    except ApiError as exc:
        if exc.status_code == 404:
            output.info(f"Tag '{tag}' not found on {package} (or feature not yet enabled).")
            return
        output.fatal(str(exc))


# ── snapshot ──────────────────────────────────────────────────────────────────
# PyPI snapshots are pre-release builds.  The canonical approach is to publish
# a version with a .devN or aN/bN suffix; rvn automates the suffix and tag.


@_snap_app.command("publish")
def pypi_snap_publish(
    dist_dir: Path = typer.Argument(Path("dist"), help="dist/ directory with built files."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    build_number: int | None = typer.Option(None, "--build", "-n", help="Override .devN suffix."),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Publish a snapshot (pre-release) build to the private index.

    The build must already have a pre-release version (a1, b1, rc1, .dev0, etc.)
    in its metadata.  This command simply uploads it and tags it as 'snapshot'.

    \b
        rvn pypi snapshot publish           # publishes dist/*.whl
        rvn pypi snapshot publish dist/     # explicit directory
    """
    api_url, slug, token = _require_token(profile, repo)
    files = list(dist_dir.glob("*.whl")) + list(dist_dir.glob("*.tar.gz"))
    if not files:
        output.fatal(f"No .whl or .tar.gz files found in {dist_dir}")

    try:
        upload_url = get_router(routing).pypi_upload_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))

    output.info("Publishing snapshot build(s) ...")
    results = pypi_reg.publish(upload_url=upload_url, token=token, files=files)
    any_fail = False
    for r in results:
        if r.ok:
            output.success(f"Snapshot published: {r.filename} ({r.version})")
        else:
            output.error(f"Failed {r.filename}: {r.detail}")
            any_fail = True
    if any_fail:
        raise typer.Exit(1)


@_snap_app.command("ls")
def pypi_snap_ls(
    package: str = typer.Argument(..., help="Package name."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """List snapshot (pre-release) versions available in the private index.

    \b
        rvn pypi snapshot ls my-pkg
    """
    api_url, slug, token = _require_token(profile, repo)
    client = _api_client(api_url, token)
    try:
        data = client.get(f"/webapp/repository/{slug}/packages/{package}/").json()
    except ApiError as exc:
        output.fatal(str(exc))

    versions: list[str] = data.get("versions", []) if isinstance(data, dict) else []
    pre_re = re.compile(r"(a|b|rc|\.dev|\.post)\d*", re.IGNORECASE)
    snapshots = [v for v in versions if pre_re.search(v)]
    if not snapshots:
        output.info(f"No snapshot versions found for {package!r}.")
        return
    output.table(["Version"], [[v] for v in snapshots], title=f"Snapshots: {package}")


# ── index-url / upload-url ────────────────────────────────────────────────────


@app.command("index-url")
def pypi_index_url(
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    with_auth: bool = typer.Option(False, "--auth", help="Embed token in URL."),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Print the private simple-index URL for use in pip / uv / Poetry.

    \b
        rvn pypi index-url
        rvn pypi index-url --auth    # includes __token__:... in URL
    """
    api_url, slug, token = _resolve(profile, repo)
    try:
        url = get_router(routing).pypi_index_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    if with_auth and token:
        url = _authed_index(url, token)
    typer.echo(url)


@app.command("upload-url")
def pypi_upload_url(
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Print the private upload URL for use with twine / uv publish.

    \b
        rvn pypi upload-url
    """
    api_url, slug, _token = _resolve(profile, repo)
    try:
        url = get_router(routing).pypi_upload_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    typer.echo(url)
