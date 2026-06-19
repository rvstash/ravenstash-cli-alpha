"""rvn sync — install all project dependencies from the manifest.

Detects the project type in the current directory and runs the right tool:

    Python (pyproject.toml)     uv sync  ->  pip install -e .
    Python (requirements.txt)   uv pip install -r requirements.txt  ->  pip install -r ...
    Node   (package.json)       npm ci / npm install (auto-selects yarn / pnpm by lock file)
    Java   (pom.xml)            mvn dependency:resolve
    Java   (build.gradle)       gradle dependencies

The private registry is injected automatically using the configured profile.
Pass --no-inject to skip injection (useful when no private packages are needed).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import typer

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import manifest as mf
from .. import output
from ..registries import npm as npm_reg
from ..registries import pypi as pypi_reg
from ..routing import RoutingMode, get_router
from ..runtimes import tools


app = typer.Typer(
    name="sync",
    help="Install all project dependencies from the manifest (auto-detects type).",
    no_args_is_help=False,
)


# ── credential helpers (mirrors run.py) ───────────────────────────────────────


def _creds(
    kind: str, profile: str | None, repo_override: str | None
) -> tuple[str, str, str] | None:
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile)
    slug = repo_override or cfg.registry_defaults(kind).default_repo  # type: ignore[arg-type]
    if not slug or not token:
        return None
    return p.api_url, slug, token


def _authed_pypi(api_url: str, slug: str, token: str) -> str:
    raw = pypi_reg.simple_index_url(api_url, slug)
    parsed = urlparse(raw)
    return urlunparse(parsed._replace(netloc=f"__token__:{token}@{parsed.netloc}"))


def _authed_npm(api_url: str, slug: str) -> str:
    return npm_reg.registry_url(api_url, slug)


# ── Python sync ───────────────────────────────────────────────────────────────


def _sync_python_pyproject(cwd: Path, creds: tuple | None, frozen: bool) -> None:
    env = {**os.environ}

    if creds:
        api_url, slug, token = creds
        authed = _authed_pypi(api_url, slug, token)
        existing = env.get("UV_EXTRA_INDEX_URL", "")
        env["UV_EXTRA_INDEX_URL"] = (existing + " " + authed).strip()
        env["PIP_EXTRA_INDEX_URL"] = authed

    uv_path = tools.resolve("uv")
    if uv_path:
        cmd = [uv_path, "sync"]
        if frozen:
            cmd.append("--frozen")
        output.info(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, cwd=str(cwd), env=env, check=True)
    else:
        cmd = [*tools.pip_cmd(), "install", "-e", "."]
        output.info(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


def _sync_python_requirements(path: Path, creds: tuple | None) -> None:
    env = {**os.environ}

    if creds:
        api_url, slug, token = creds
        authed = _authed_pypi(api_url, slug, token)
        env["UV_EXTRA_INDEX_URL"] = authed
        env["PIP_EXTRA_INDEX_URL"] = authed

    cmd = [*tools.pip_cmd(), "install", "-r", str(path)]
    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, env=env, check=True)


# ── Node sync ─────────────────────────────────────────────────────────────────


def _detect_node_pm(cwd: Path) -> str:
    if (cwd / "pnpm-lock.yaml").exists() and tools.resolve("pnpm"):
        return "pnpm"
    if (cwd / "yarn.lock").exists() and tools.resolve("yarn"):
        return "yarn"
    return "npm"


def _sync_node(cwd: Path, creds: tuple | None, frozen: bool) -> None:
    pm = _detect_node_pm(cwd)
    env = {**os.environ}

    if creds:
        api_url, slug, token = creds
        reg_url = _authed_npm(api_url, slug)
        host = urlparse(reg_url).netloc
        env[f"NPM_CONFIG_//{host}/:_authToken"] = token
        if pm == "yarn":
            env["YARN_REGISTRY"] = reg_url
            env["YARN_NPM_REGISTRY_SERVER"] = reg_url
            env["YARN_NPM_AUTH_TOKEN"] = token
        elif pm == "pnpm":
            env["npm_config_registry"] = reg_url

    lock_exists = {
        "npm": (cwd / "package-lock.json").exists(),
        "yarn": True,  # yarn install --frozen-lockfile works without lock
        "pnpm": True,
    }

    if pm == "pnpm":
        cmd = ["pnpm", "install"]
        if frozen and (cwd / "pnpm-lock.yaml").exists():
            cmd.append("--frozen-lockfile")
    elif pm == "yarn":
        cmd = ["yarn", "install"]
        if frozen:
            cmd.append("--frozen-lockfile")
    else:
        # npm: prefer ci (reproducible) when lock file exists
        npm_bin = tools.npm()
        if frozen and lock_exists["npm"]:
            cmd = [npm_bin, "ci"]
        else:
            cmd = [npm_bin, "install"]

    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


# ── Java sync ─────────────────────────────────────────────────────────────────


def _sync_java_maven(cwd: Path, creds: tuple | None) -> None:
    import tempfile

    cmd = [tools.mvn(), "dependency:resolve", "-q"]

    if creds:
        from ..registries import maven as maven_reg

        api_url, slug, token = creds
        repo_url = maven_reg.repo_url(api_url, slug)
        settings_xml = maven_reg._build_settings_xml(repo_url, token, "rvn-sync")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", prefix="rvn-settings-", delete=False
        ) as f:
            f.write(settings_xml)
            settings_path = f.name
        cmd.extend(["--settings", settings_path])
    else:
        settings_path = None

    output.info(f"Running: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, cwd=str(cwd), check=True)
    finally:
        if settings_path:
            Path(settings_path).unlink(missing_ok=True)


def _sync_java_gradle(cwd: Path, creds: tuple | None) -> None:
    import tempfile

    tool = "gradlew" if (cwd / "gradlew").exists() else "gradle"
    cmd = [f"./{tool}" if tool == "gradlew" else tool, "dependencies", "--quiet"]

    if creds:
        api_url, slug, token = creds
        from ..registries import maven as maven_reg

        repo_url = maven_reg.repo_url(api_url, slug)
        init_script = (
            "allprojects {\n"
            "  buildscript { repositories { maven { "
            "url '" + repo_url + "'\n"
            "credentials { username '__token__'; password '" + token + "' } } } }\n"
            "  repositories { maven { "
            "url '" + repo_url + "'\n"
            "credentials { username '__token__'; password '" + token + "' } } }\n"
            "}\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".gradle", prefix="rvn-init-", delete=False
        ) as f:
            f.write(init_script)
            init_path = f.name
        cmd.extend(["--init-script", init_path])
    else:
        init_path = None

    output.info(f"Running: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, cwd=str(cwd), check=True)
    finally:
        if init_path:
            Path(init_path).unlink(missing_ok=True)


# ── Main command ──────────────────────────────────────────────────────────────


@app.callback(invoke_without_command=True)
def sync(
    profile: str | None = typer.Option(None, "--profile", "-p", help="Config profile to use."),
    repo: str | None = typer.Option(
        None, "--repo", "-r", help="Override the default repository slug."
    ),
    frozen: bool = typer.Option(
        True, "--frozen/--no-frozen", help="Require lock file to be up-to-date (default: on)."
    ),
    no_inject: bool = typer.Option(False, "--no-inject", help="Skip private registry injection."),
    directory: Path = typer.Option(
        Path("."), "--directory", "-C", help="Project directory (default: cwd)."
    ),
    routing: RoutingMode = typer.Option(
        "canonical",
        "--routing",
        help="URL routing: canonical (default) | unified (not yet implemented).",
    ),
) -> None:
    """Install all project dependencies from the manifest.

    Automatically detects the project type and runs:

    \b
        pyproject.toml  →  uv sync (or pip install -e .)
        requirements.txt → uv pip install -r requirements.txt
        package.json    →  npm ci / npm install (or yarn / pnpm)
        pom.xml         →  mvn dependency:resolve
        build.gradle    →  gradle dependencies
    """
    cwd = directory.resolve()
    info = mf.detect(cwd)
    if info is None:
        output.fatal(
            "No project manifest found. "
            "Expected pyproject.toml, requirements.txt, package.json, pom.xml, or build.gradle."
        )

    # Validate routing mode — fails immediately if unified (not yet implemented).
    try:
        get_router(routing)
    except NotImplementedError as exc:
        output.fatal(str(exc))

    kind_label = {"python": "Python", "node": "Node", "java": "Java"}[info.eco]
    output.info(f"Detected {kind_label} project ({info.path.name})")

    creds: tuple | None = None
    if not no_inject:
        # Map eco → registry kind
        eco_to_kind = {"python": "pypi", "node": "npm", "java": "maven"}
        kind = eco_to_kind[info.eco]
        creds = _creds(kind, profile, repo)
        if creds is None:
            output.warn(
                "No registry credentials configured — syncing without private registry.\n"
                "Run `rvn auth login` or set a default repo with `rvn auth add-registry`."
            )

    if info.eco == "python":
        if info.kind == "pyproject":
            _sync_python_pyproject(cwd, creds, frozen)
        else:
            _sync_python_requirements(info.path, creds)
    elif info.eco == "node":
        _sync_node(cwd, creds, frozen)
    elif info.eco == "java":
        if info.kind == "pom_xml":
            _sync_java_maven(cwd, creds)
        else:
            _sync_java_gradle(cwd, creds)

    output.success("Sync complete.")
