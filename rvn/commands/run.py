"""rvn run — transparent native package-manager runner with private registry injection.

Usage
-----
    rvn run [--profile <p>] [--repo <slug>] [--no-inject] <tool> [tool-args...]

Supported tools and their injection strategy
--------------------------------------------

pip / pip3
    ``pip install`` / ``pip download`` → ``--extra-index-url <auth-url>``
    All other pip sub-commands pass through unchanged.

uv
    All sub-commands receive the private index via the ``UV_EXTRA_INDEX_URL``
    environment variable (uv honours this for sync, run, pip install, add, …).
    For ``uv pip install`` / ``uv pip download`` the flag is also injected
    directly so it is listed in any --dry-run output.

npm
    ``npm install`` / ``npm ci`` / ``npm publish`` →
        ``--registry <url>``  + ``NPM_CONFIG_//{host}/:_authToken`` env var.
    All other npm sub-commands receive the env var but no extra flag.

yarn (v1 & v2/berry)
    Registry + auth injected via ``YARN_REGISTRY`` / ``YARN_NPM_REGISTRY_SERVER``
    env vars and the ``npm_config_//{host}/:_authToken`` env var.

pnpm
    ``pnpm install`` / ``pnpm add`` / ``pnpm publish`` →
        ``--registry <url>``  + auth env var.

mvn / mvnw
    A temporary ``settings.xml`` is written to a temp file, injected as
    ``mvn --settings <path>`` and deleted after the command exits.

gradle / gradlew
    A temporary Groovy init script that adds the private Maven repository to
    ``allprojects { repositories { ... } }`` is injected as
    ``gradle --init-script <path>`` and deleted after the command exits.

sbt
    Credentials + resolver injected via ``SBT_CREDENTIALS`` and
    ``SBT_OPTS`` (resolvers are set via sys.props in the opts string).

Unknown tools
    A warning is printed and the tool is run without any injection.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import output
from ..registries import maven as maven_reg
from ..registries import npm as npm_reg
from ..registries import pypi as pypi_reg
from ..runtimes import tools as _tools


# ── Credential resolution ─────────────────────────────────────────────────────


def _resolve(
    kind: str,
    repo_override: str | None,
    profile: str | None,
) -> tuple[str, str, str] | None:
    """Return (api_url, slug, token) or None if nothing is configured."""
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile)
    slug = repo_override or cfg.registry_defaults(kind).default_repo  # type: ignore[arg-type]
    if not slug or not token:
        return None
    return p.api_url, slug, token


def _authed_index(api_url: str, slug: str, token: str) -> str:
    """Build an HTTP-Basic-authed simple-index URL for pip/uv."""
    from urllib.parse import urlparse, urlunparse

    raw = pypi_reg.simple_index_url(api_url, slug)
    parsed = urlparse(raw)
    return urlunparse(parsed._replace(netloc=f"__token__:{token}@{parsed.netloc}"))


# ── Per-tool runners ──────────────────────────────────────────────────────────


def _run_pip(tool: str, tool_args: list[str], creds: tuple | None) -> None:
    """pip / pip3 — inject --extra-index-url for install and download."""
    bin = _tools.resolve(tool) or tool
    cmd = [bin, *tool_args]
    if creds and tool_args and tool_args[0] in ("install", "download"):
        api_url, slug, token = creds
        authed = _authed_index(api_url, slug, token)
        cmd = [bin, tool_args[0], "--extra-index-url", authed, *tool_args[1:]]
    subprocess.run(cmd, check=True)


def _run_uv(tool_args: list[str], creds: tuple | None) -> None:
    """uv — inject private index via UV_EXTRA_INDEX_URL env var.

    Also injects --extra-index-url directly for ``uv pip install`` /
    ``uv pip download`` so it appears in dry-run output and uv's own logs.
    """
    env = {**os.environ}
    uv_bin = _tools.resolve("uv") or "uv"
    cmd = [uv_bin, *tool_args]

    if creds:
        api_url, slug, token = creds
        authed = _authed_index(api_url, slug, token)

        # Env var covers all uv sub-commands (sync, run, add, lock, …)
        existing = env.get("UV_EXTRA_INDEX_URL", "")
        env["UV_EXTRA_INDEX_URL"] = f"{authed} {existing}".strip() if existing else authed

        # Also inject the flag directly for uv pip install / uv pip download
        if (
            len(tool_args) >= 2
            and tool_args[0] == "pip"
            and tool_args[1] in ("install", "download", "sync")
        ):
            cmd = [uv_bin, tool_args[0], tool_args[1], "--extra-index-url", authed, *tool_args[2:]]

    subprocess.run(cmd, env=env, check=True)


def _run_npm(tool_args: list[str], creds: tuple | None) -> None:
    """npm — inject --registry flag + auth env var for install/ci/publish."""
    from urllib.parse import urlparse

    env = {**os.environ}
    npm_bin = _tools.resolve("npm") or "npm"
    cmd = [npm_bin, *tool_args]

    if creds:
        api_url, slug, token = creds
        registry = npm_reg.registry_url(api_url, slug)
        host = urlparse(registry).netloc
        env[f"NPM_CONFIG_//{host}/:_authToken"] = token

        if tool_args and tool_args[0] in ("install", "i", "ci", "publish", "pack"):
            cmd = [npm_bin, tool_args[0], "--registry", registry, *tool_args[1:]]

    subprocess.run(cmd, env=env, check=True)


def _run_yarn(tool_args: list[str], creds: tuple | None) -> None:
    """yarn (v1 and v2/berry) — inject registry + auth via env vars."""
    from urllib.parse import urlparse

    env = {**os.environ}

    if creds:
        api_url, slug, token = creds
        registry = npm_reg.registry_url(api_url, slug)
        host = urlparse(registry).netloc
        # Yarn v1
        env["YARN_REGISTRY"] = registry
        env[f"npm_config_//{host}/:_authToken"] = token
        # Yarn v2/berry (uses YARN_NPM_REGISTRY_SERVER)
        env["YARN_NPM_REGISTRY_SERVER"] = registry
        env["YARN_NPM_AUTH_TOKEN"] = token

    subprocess.run(["yarn", *tool_args], env=env, check=True)


def _run_pnpm(tool_args: list[str], creds: tuple | None) -> None:
    """pnpm — inject --registry flag + auth env var for install/add/publish."""
    from urllib.parse import urlparse

    env = {**os.environ}
    cmd = ["pnpm", *tool_args]

    if creds:
        api_url, slug, token = creds
        registry = npm_reg.registry_url(api_url, slug)
        host = urlparse(registry).netloc
        env[f"npm_config_//{host}/:_authToken"] = token

        if tool_args and tool_args[0] in ("install", "i", "add", "publish"):
            cmd = ["pnpm", tool_args[0], "--registry", registry, *tool_args[1:]]

    subprocess.run(cmd, env=env, check=True)


def _run_mvn(tool: str, tool_args: list[str], creds: tuple | None) -> None:
    """mvn / mvnw — inject private repo via a temporary settings.xml."""
    # mvnw is a local wrapper script — use it as-is; for mvn use managed runtime.
    mvn_bin = tool if tool == "mvnw" else (_tools.resolve("mvn") or tool)
    if not creds:
        subprocess.run([mvn_bin, *tool_args], check=True)
        return

    api_url, slug, token = creds
    repo_url = maven_reg.repo_url(api_url, slug)
    from ..registries.maven import _build_settings_xml

    xml = _build_settings_xml(repo_url, token)

    with tempfile.NamedTemporaryFile(
        suffix=".xml", mode="w", delete=False, prefix="rvn-settings-"
    ) as f:
        f.write(xml)
        settings_path = f.name

    try:
        subprocess.run([mvn_bin, f"--settings={settings_path}", *tool_args], check=True)
    finally:
        Path(settings_path).unlink(missing_ok=True)


def _run_gradle(tool: str, tool_args: list[str], creds: tuple | None) -> None:
    """gradle / gradlew — inject private Maven repo via a temp init script."""
    if not creds:
        subprocess.run([tool, *tool_args], check=True)
        return

    api_url, slug, token = creds
    repo_url = maven_reg.repo_url(api_url, slug)

    # Groovy init script — safe string interpolation (no user-controlled data in template)
    init_script = (
        "allprojects {\n"
        "    repositories {\n"
        "        maven {\n"
        f"            url '{repo_url}'\n"
        "            credentials {\n"
        "                username '__token__'\n"
        f"                password '{token}'\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "    buildscript {\n"
        "        repositories {\n"
        "            maven {\n"
        f"                url '{repo_url}'\n"
        "                credentials {\n"
        "                    username '__token__'\n"
        f"                    password '{token}'\n"
        "                }\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    with tempfile.NamedTemporaryFile(
        suffix=".gradle", mode="w", delete=False, prefix="rvn-init-"
    ) as f:
        f.write(init_script)
        init_path = f.name

    try:
        subprocess.run([tool, f"--init-script={init_path}", *tool_args], check=True)
    finally:
        Path(init_path).unlink(missing_ok=True)


def _run_sbt(tool_args: list[str], creds: tuple | None) -> None:
    """sbt — inject credentials via SBT_CREDENTIALS and extra resolvers via SBT_OPTS."""
    env = {**os.environ}

    if creds:
        api_url, slug, token = creds
        repo_url = maven_reg.repo_url(api_url, slug)

        # Write sbt credentials file
        creds_content = (
            f"realm=rvn-private\n"
            f"host={repo_url.split('//')[-1].split('/')[0]}\n"
            f"user=__token__\n"
            f"password={token}\n"
        )
        with tempfile.NamedTemporaryFile(
            suffix=".sbt-creds", mode="w", delete=False, prefix="rvn-"
        ) as f:
            f.write(creds_content)
            creds_path = f.name

        env["SBT_CREDENTIALS"] = creds_path
        # Inject resolver via JVM system property (picked up by sbt's build definition)
        existing_opts = env.get("SBT_OPTS", "")
        env["SBT_OPTS"] = (
            f"{existing_opts} -Drvn.resolver.url={repo_url} -Drvn.resolver.name=rvn-private"
        ).strip()

    try:
        subprocess.run(["sbt", *tool_args], env=env, check=True)
    finally:
        if creds:
            Path(creds_path).unlink(missing_ok=True)  # type: ignore[possibly-undefined]


# ── Dispatch table ────────────────────────────────────────────────────────────

# tool_name → (registry_kind, dispatcher_fn)
_DISPATCHERS: dict[str, tuple[str, object]] = {
    "pip": ("pypi", lambda t, a, c: _run_pip(t, a, c)),
    "pip3": ("pypi", lambda t, a, c: _run_pip(t, a, c)),
    "uv": ("pypi", lambda t, a, c: _run_uv(a, c)),
    "npm": ("npm", lambda t, a, c: _run_npm(a, c)),
    "yarn": ("npm", lambda t, a, c: _run_yarn(a, c)),
    "pnpm": ("npm", lambda t, a, c: _run_pnpm(a, c)),
    "mvn": ("maven", lambda t, a, c: _run_mvn(t, a, c)),
    "mvnw": ("maven", lambda t, a, c: _run_mvn(t, a, c)),
    "gradle": ("maven", lambda t, a, c: _run_gradle(t, a, c)),
    "gradlew": ("maven", lambda t, a, c: _run_gradle(t, a, c)),
    "sbt": ("maven", lambda t, a, c: _run_sbt(a, c)),
}


# ── CLI command (registered directly on the root app in cli.py) ───────────────


def run_tool(
    ctx: typer.Context,
    profile: Annotated[
        str | None,
        typer.Option("--profile", "-p", help="Config profile to use for registry credentials."),
    ] = None,
    repo: Annotated[
        str | None,
        typer.Option("--repo", "-r", help="Override the default repository slug."),
    ] = None,
    kind: Annotated[
        str | None,
        typer.Option("--kind", "-k", help="Force registry kind: pypi | npm | maven."),
    ] = None,
    no_inject: Annotated[
        bool,
        typer.Option(
            "--no-inject", help="Run the tool without injecting any private registry config."
        ),
    ] = False,
) -> None:
    """Run a native package manager with the private registry automatically injected.

    rvn run intercepts the command, injects your private registry credentials
    transparently, then execs the real tool with its full output and behaviour
    preserved.

    \b
    Supported tools:
        pip / pip3   — Python (PyPI)
        uv           — Python (PyPI) — all sub-commands (sync, run, add, lock, …)
        npm          — Node (npm)
        yarn         — Node (npm, v1 and v2/berry)
        pnpm         — Node (npm)
        mvn / mvnw   — JVM (Maven)
        gradle / gradlew — JVM (Maven)
        sbt          — JVM (Maven)

    \b
    Examples:
        rvn run pip install requests
        rvn run pip install mylib --extra-index-url https://pypi.org/simple
        rvn run uv sync
        rvn run uv pip install mylib==1.2
        rvn run uv run pytest
        rvn run uv add mylib
        rvn run npm install lodash
        rvn run npm publish
        rvn run yarn install
        rvn run pnpm add @scope/utils
        rvn run mvn clean install
        rvn run mvn deploy
        rvn run gradle build
        rvn run gradle publishToMavenLocal
        rvn run --repo my-pypi uv sync
        rvn run --no-inject pip install requests
    """
    args = list(ctx.args)
    if not args:
        output.fatal(
            "Specify a tool to run.\n\n"
            "  rvn run pip install requests\n"
            "  rvn run uv sync\n"
            "  rvn run uv run pytest\n"
            "  rvn run npm install lodash\n"
            "  rvn run mvn clean install\n"
            "  rvn run gradle build\n"
        )

    tool = args[0]
    tool_args = args[1:]

    entry = _DISPATCHERS.get(tool.lower())
    if not entry:
        output.warn(f"'{tool}' is not a recognised tool — running without registry injection.")
        try:
            subprocess.run([tool, *tool_args], check=True)
        except FileNotFoundError:
            output.fatal(f"'{tool}' not found in PATH.")
        except subprocess.CalledProcessError as exc:
            raise typer.Exit(exc.returncode) from exc
        return

    auto_kind, dispatcher = entry
    resolved_kind = kind or auto_kind

    creds: tuple | None = None
    if not no_inject:
        creds = _resolve(resolved_kind, repo, profile)
        if creds:
            _, slug, _ = creds
            output.info(f"[{tool}] → private {resolved_kind} registry [{slug}]")
        else:
            output.warn(
                f"No {resolved_kind} repository configured for this profile. "
                f"Running {tool} without private registry injection.\n"
                f"  Hint: rvn auth add-registry --kind {resolved_kind} --repo <slug>"
            )

    try:
        dispatcher(tool, tool_args, creds)  # type: ignore[call-arg]
    except subprocess.CalledProcessError as exc:
        raise typer.Exit(exc.returncode) from exc
    except FileNotFoundError:
        output.fatal(f"'{tool}' not found in PATH. Is it installed?")
