"""rvn java — Java/JVM ecosystem commands.

Project lifecycle + Maven/Gradle registry commands in one place:

    rvn java sync                               # mvn dependency:resolve / gradle dependencies
    rvn java add com.google.guava:guava:33.0    # add to pom.xml / build.gradle
    rvn java remove com.google.guava:guava      # remove from pom.xml / build.gradle
    rvn java pin 21                             # install Java 21 via SDKMAN
    rvn java install com.example:mylib:1.0      # fetch from private registry
    rvn java deploy mylib.jar                   # deploy to private Maven registry
    rvn java repo-url                           # print private Maven repo URL
    rvn java settings-xml                       # print Maven settings.xml snippet
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import typer

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import manifest as mf
from .. import output
from ..registries import maven as maven_reg
from ..routing import RoutingMode, get_router
from ..runtimes import tools
from ..semver import bump_semver, validate_bump_part


app = typer.Typer(
    name="java",
    help="Java/JVM ecosystem — project lifecycle + Maven registry.",
    no_args_is_help=True,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _creds(profile: str | None, repo: str | None) -> tuple | None:
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile)
    slug = repo or cfg.registry_defaults("maven").default_repo
    if not slug or not token:
        return None
    return p.api_url, slug, token


def _detect_build(cwd: Path) -> str:
    if (cwd / "build.gradle").exists() or (cwd / "build.gradle.kts").exists():
        return "gradle"
    return "mvn"


def _mvn_with_settings(base_cmd: list[str], creds: tuple | None) -> list[str]:
    """Return (cmd, settings_path_or_None).  Caller must clean up settings_path."""
    return base_cmd  # see context manager version below


# ── sync ──────────────────────────────────────────────────────────────────────


@app.command("sync")
def java_sync(
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
    """Resolve and download all Maven/Gradle project dependencies.

    \b
        pom.xml         → mvn dependency:resolve
        build.gradle    → gradle dependencies
    """
    cwd = directory.resolve()
    info = mf.detect(cwd)
    if info is None or info.eco != "java":
        output.fatal("No Java manifest found (pom.xml or build.gradle).")

    creds: tuple | None = None
    if not no_inject:
        creds = _creds(profile, repo)
        if creds is None:
            output.warn("No registry credentials — resolving from public repositories only.")

    settings_path: str | None = None
    init_path: str | None = None

    try:
        if info.kind == "pom_xml":
            cmd = [tools.mvn(), "dependency:resolve", "-q"]
            if creds:
                api_url, slug, token = creds
                try:
                    repo_url = get_router(routing).maven_repo_url(api_url, slug)
                except NotImplementedError as exc:
                    output.fatal(str(exc))
                xml = maven_reg._build_settings_xml(repo_url, token, "rvn-sync")
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".xml", prefix="rvn-settings-", delete=False
                ) as f:
                    f.write(xml)
                    settings_path = f.name
                cmd.extend(["--settings", settings_path])
        else:
            tool = "gradlew" if (cwd / "gradlew").exists() else "gradle"
            exe = f"./{tool}" if tool == "gradlew" else tool
            cmd = [exe, "dependencies", "--quiet"]
            if creds:
                api_url, slug, token = creds
                try:
                    repo_url = get_router(routing).maven_repo_url(api_url, slug)
                except NotImplementedError as exc:
                    output.fatal(str(exc))
                init_script = (
                    "allprojects {\n"
                    "  buildscript { repositories { maven { "
                    "url '" + repo_url + "'\n"
                    "    credentials { username '__token__'; password '" + token + "' }\n"
                    "  } } }\n"
                    "  repositories { maven {\n"
                    "    url '" + repo_url + "'\n"
                    "    credentials { username '__token__'; password '" + token + "' }\n"
                    "  } }\n"
                    "}\n"
                )
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".gradle", prefix="rvn-init-", delete=False
                ) as f:
                    f.write(init_script)
                    init_path = f.name
                cmd.extend(["--init-script", init_path])

        output.info(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, cwd=str(cwd), check=True)
        output.success("Sync complete.")
    finally:
        if settings_path:
            Path(settings_path).unlink(missing_ok=True)
        if init_path:
            Path(init_path).unlink(missing_ok=True)


# ── add / remove ──────────────────────────────────────────────────────────────


@app.command("add")
def java_add(
    coords: str = typer.Argument(..., help="Maven coordinates: groupId:artifactId:version[:scope]"),
    config: str = typer.Option(
        "implementation", help="Gradle configuration (e.g. testImplementation)."
    ),
    no_sync: bool = typer.Option(
        False, "--no-sync", help="Update manifest only; skip dependency:get."
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
    routing: RoutingMode = typer.Option(
        "canonical",
        "--routing",
        help="URL routing: canonical (default) | unified (not yet implemented).",
    ),
) -> None:
    """Add a Maven dependency to pom.xml or build.gradle.

    \b
        rvn java add com.google.guava:guava:33.0.0-jre
        rvn java add org.junit.jupiter:junit-jupiter:5.10.0:test
    """
    cwd = directory.resolve()
    info = mf.detect(cwd)
    if info is None or info.eco != "java":
        output.fatal("No Java manifest found (pom.xml or build.gradle).")

    if info.kind == "gradle":
        changed = mf.gradle_add_dep(info.path, coords, configuration=config)
    else:
        changed = mf.pom_xml_add_dep(info.path, coords)

    if changed:
        output.success(f"Added '{coords}' to {info.path.name}")
    else:
        output.warn(f"Could not add '{coords}' — check manifest format.")

    if no_sync:
        return

    # Fetch the artifact so it lands in the local repo
    parts = coords.split(":")
    if len(parts) < 3:
        output.info("Skipping pre-fetch: version not specified.")
        return

    creds = _creds(profile, repo)
    settings_path: str | None = None
    cmd = [tools.mvn(), "dependency:get", f"-Dartifact={coords}", "-q"]

    try:
        if creds:
            api_url, slug, token = creds
            try:
                repo_url = get_router(routing).maven_repo_url(api_url, slug)
            except NotImplementedError as exc:
                output.fatal(str(exc))
            xml = maven_reg._build_settings_xml(repo_url, token, "rvn-add")
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".xml", prefix="rvn-settings-", delete=False
            ) as f:
                f.write(xml)
                settings_path = f.name
            cmd.extend(["--settings", settings_path])

        output.info(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
    finally:
        if settings_path:
            Path(settings_path).unlink(missing_ok=True)


@app.command("remove")
def java_remove(
    coords: str = typer.Argument(..., help="groupId:artifactId (version optional)."),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
) -> None:
    """Remove a Maven/Gradle dependency from the manifest."""
    cwd = directory.resolve()
    info = mf.detect(cwd)
    if info is None or info.eco != "java":
        output.fatal("No Java manifest found.")

    removed = mf.remove_dep(info, coords)
    if removed:
        output.success(f"Removed '{coords}' from {info.path.name}")
        output.info("Run `rvn java sync` to refresh the resolved dependency tree.")
    else:
        output.warn(f"'{coords}' not found in {info.path.name}")
        raise typer.Exit(1)


# ── pin (runtime version) ─────────────────────────────────────────────────────


@app.command("pin")
def java_pin(
    version: str = typer.Argument(..., help="Java version string, e.g. '21' or '21.0.3-tem'."),
    distribution: str | None = typer.Option(
        None,
        "--dist",
        "-d",
        help="SDKMAN distribution suffix, e.g. 'graalce', 'tem', 'zulu'.  "
        "Combined as <version>.<distribution> if provided.",
    ),
    write_file: bool = typer.Option(
        True, "--write-file/--no-write-file", help="Write .java-version."
    ),
) -> None:
    """Install a Java runtime via SDKMAN and pin it for the project.

    \b
        rvn java pin 21
        rvn java pin 21.0.3 --dist tem
        rvn java pin 21.0.3-graalce

    Requires SDKMAN (https://sdkman.io/).
    """
    sdk_version = f"{version}.{distribution}" if distribution else version

    if shutil.which("sdk"):
        output.info(f"Running: sdk install java {sdk_version}")
        # sdk is a shell function; invoke via bash so it is sourced properly
        script = f'source "$HOME/.sdkman/bin/sdkman-init.sh" && sdk install java {sdk_version}'
        result = subprocess.run(["bash", "-c", script], check=False)
        if result.returncode not in (0, 1):  # sdk returns 1 when already installed
            output.warn(f"sdk install exited with code {result.returncode}")
    else:
        output.warn(
            "SDKMAN not found.  Install it: https://sdkman.io/\n"
            f"Then run:  sdk install java {sdk_version}"
        )
        if write_file:
            Path(".java-version").write_text(version + "\n")
            output.info(f"Wrote .java-version = {version}")
        raise typer.Exit(1)

    if write_file:
        Path(".java-version").write_text(version + "\n")
        output.info("Wrote .java-version")

    output.success(f"Java {sdk_version} ready.")


# ── install (fetch artifact from private registry) ────────────────────────────


@app.command("install")
def java_install(
    coords: str = typer.Argument(..., help="Maven coordinates: groupId:artifactId:version."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option(
        "canonical",
        "--routing",
        help="URL routing: canonical (default) | unified (not yet implemented).",
    ),
) -> None:
    """Fetch a Maven artifact from the private registry into the local repo."""
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile)
    slug = repo or cfg.registry_defaults("maven").default_repo
    if not slug:
        output.fatal("No repository configured. Pass --repo or set a default.")
    if not token:
        output.fatal("Not authenticated. Run `rvn auth login` first.")

    try:
        repo_url = get_router(routing).maven_repo_url(p.api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))

    maven_reg.install(
        repo_url=repo_url,
        token=token,
        coords=coords,
    )


# ── deploy ────────────────────────────────────────────────────────────────────


@app.command("deploy")
def java_deploy(
    jar: Path = typer.Argument(..., help="JAR (or WAR/POM) file to deploy."),
    group: str = typer.Option(..., "--group", "-g", help="Maven groupId."),
    artifact: str = typer.Option(..., "--artifact", "-a", help="Maven artifactId."),
    version: str = typer.Option(..., "--version", "-v", help="Version string."),
    packaging: str = typer.Option("jar", "--packaging", help="Packaging type."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option(
        "canonical",
        "--routing",
        help="URL routing: canonical (default) | unified (not yet implemented).",
    ),
) -> None:
    """Deploy a Maven artifact to the private registry."""
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile)
    slug = repo or cfg.registry_defaults("maven").default_repo
    if not slug:
        output.fatal("No repository configured.")
    if not token:
        output.fatal("Not authenticated. Run `rvn auth login`.")

    try:
        upload_url = get_router(routing).maven_repo_url(p.api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    results = maven_reg.publish(
        upload_url=upload_url,
        token=token,
        group_id=group,
        artifact_id=artifact,
        version=version,
        files=[jar],
    )
    any_fail = False
    for r in results:
        if r.ok:
            output.success(f"Deployed {r.filename}")
        else:
            output.error(f"Failed {r.filename}: {r.detail}")
            any_fail = True
    if any_fail:
        raise typer.Exit(1)


# ── repo-url / settings-xml ───────────────────────────────────────────────────


@app.command("repo-url")
def java_repo_url(
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Print the private Maven repository URL."""
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    slug = repo or cfg.registry_defaults("maven").default_repo
    if not slug:
        output.fatal("No repository configured.")
    typer.echo(maven_reg.repo_url(p.api_url, slug))


@app.command("settings-xml")
def java_settings_xml(
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    server_id: str = typer.Option("rvn", "--server-id", help="Maven server id."),
) -> None:
    """Print a Maven settings.xml snippet for this registry."""
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    slug = repo or cfg.registry_defaults("maven").default_repo
    if not slug:
        output.fatal("No repository configured.")

    repo_url = maven_reg.repo_url(p.api_url, slug)
    typer.echo(maven_reg._build_settings_xml(repo_url, "${RVN_TOKEN}", server_id))


# ── yank ──────────────────────────────────────────────────────────────────────


@app.command("yank")
def java_yank(
    coords: str = typer.Argument(..., help="Maven coordinates: groupId:artifactId:version."),
) -> None:
    """[Not supported] The Maven protocol does not support yanking.

    To prevent use of a published artifact, delete it via `rvn pkg delete`.
    """
    output.error(
        "The Maven registry protocol does not support yanking.\n"
        "  To remove an artifact, use `rvn pkg delete`."
    )
    raise typer.Exit(1)


# ── deprecate ─────────────────────────────────────────────────────────────────


@app.command("deprecate")
def java_deprecate(
    coords: str = typer.Argument(..., help="Maven coordinates: groupId:artifactId:version."),
    message: str = typer.Argument(..., help="Deprecation message."),
) -> None:
    """[Not supported] The Maven protocol does not support deprecation.

    To prevent use of a published artifact, delete it via `rvn pkg delete`.
    """
    output.error(
        "The Maven registry protocol does not support deprecation.\n"
        "  To remove an artifact, use `rvn pkg delete`."
    )
    raise typer.Exit(1)


# ── bump ──────────────────────────────────────────────────────────────────────


@app.command("bump")
def java_bump(
    part: str = typer.Argument(..., help="Version part to bump: major | minor | patch."),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
) -> None:
    """Bump the pom.xml project version.

    Uses `mvn versions:set` when Maven is available; falls back to direct
    text replacement for single-module projects.

    \b
        rvn java bump patch     # 1.2.3 → 1.2.4
        rvn java bump minor     # 1.2.3 → 1.3.0
        rvn java bump major     # 1.2.3 → 2.0.0
    """
    validate_bump_part(part)

    cwd = directory.resolve()
    pom = cwd / "pom.xml"
    if not pom.exists():
        output.fatal(
            "No pom.xml found. Gradle version bumping is not yet supported.\n"
            "  For Gradle projects, update the version manually in build.gradle."
        )

    content = pom.read_text()
    m = re.search(r"<version>([^<]+)</version>", content)
    if not m:
        output.fatal("Could not find <version>...</version> in pom.xml.")

    old_version = m.group(1).strip()
    new_version = bump_semver(old_version, part)

    mvn_path = tools.resolve("mvn")
    if mvn_path:
        cmd = [
            mvn_path,
            "versions:set",
            f"-DnewVersion={new_version}",
            "-DgenerateBackupPoms=false",
            "-q",
        ]
        output.info(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=str(cwd), check=False)
        if result.returncode != 0:
            output.fatal(f"mvn versions:set failed (exit {result.returncode}).")
    else:
        # Fallback: replace first <version> occurrence directly
        new_content = content[: m.start(1)] + new_version + content[m.end(1) :]
        pom.write_text(new_content)

    output.success(f"Bumped version: {old_version} → {new_version}")
