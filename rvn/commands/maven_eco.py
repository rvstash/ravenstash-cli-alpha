"""rvn maven — comprehensive Maven registry + Java/JVM project lifecycle.

All registry operations for Maven artifacts.  Canonical Maven protocol routes
are fully functional; unified routes (marked with ✦) are wired to the
Ravenstash API and will be enabled when server-side endpoints are deployed.

    rvn maven install com.google.guava:guava:33.0   # fetch artifact
    rvn maven sync                                   # mvn dependency:resolve
    rvn maven add com.google.guava:guava:33.0        # add to pom.xml
    rvn maven remove com.google.guava:guava          # remove from pom.xml
    rvn maven deploy mylib.jar --group ... --artifact ... --version ...
    rvn maven yank com.example:mylib:1.0.0          # ✦ unified API
    rvn maven deprecate com.example:mylib:1.0.0 "msg"  # ✦ unified API
    rvn maven bump patch                             # 1.2.3 → 1.2.4 in pom.xml
    rvn maven dist-tag add com.example:mylib:1.0.0 stable  # ✦ unified
    rvn maven snapshot deploy mylib.jar             # mvn deploy with -SNAPSHOT
    rvn maven snapshot ls com.example:mylib         # list SNAPSHOT versions
    rvn maven repo-url                              # print Maven repo URL
    rvn maven settings-xml                          # print settings.xml snippet
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import typer

from .. import manifest as mf
from .. import output
from ..client import ApiError
from ..registries import maven as maven_reg
from ..routing import RoutingMode, get_router
from ..runtimes import tools
from ..semver import bump_semver, validate_bump_part
from ._eco_helpers import api_client as _api_client
from ._eco_helpers import require_token as _eco_require_token
from ._eco_helpers import resolve_registry as _resolve_registry


app = typer.Typer(
    name="maven",
    help="Maven registry — install, deploy, yank, dist-tags, snapshots, and project lifecycle.",
    no_args_is_help=True,
)

_tag_app = typer.Typer(no_args_is_help=True, help="Manage distribution tags (release, beta, etc.)")
_snap_app = typer.Typer(no_args_is_help=True, help="Manage SNAPSHOT builds.")

app.add_typer(_tag_app, name="dist-tag")
app.add_typer(_snap_app, name="snapshot")


def _resolve(
    profile: str | None,
    repo: str | None,
) -> tuple[str, str, str | None]:
    return _resolve_registry("maven", profile, repo)


def _require_token(profile: str | None, repo: str | None) -> tuple[str, str, str]:
    return _eco_require_token("maven", profile, repo)


# ── Credential helpers ────────────────────────────────────────────────────────


def _detect_build(cwd: Path) -> str:
    if (cwd / "build.gradle").exists() or (cwd / "build.gradle.kts").exists():
        return "gradle"
    return "mvn"


def _write_settings(repo_url: str, token: str, server_id: str = "rvn") -> str:
    """Write a temp settings.xml and return its path. Caller must unlink."""
    xml = maven_reg._build_settings_xml(repo_url, token, server_id)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", prefix="rvn-settings-", delete=False
    ) as f:
        f.write(xml)
        return f.name


# ── install ───────────────────────────────────────────────────────────────────


@app.command("install")
def maven_install(
    coords: str = typer.Argument(..., help="Maven coordinates: groupId:artifactId:version."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Fetch a Maven artifact into the local repository (~/.m2).

    \b
        rvn maven install com.google.guava:guava:33.0.0-jre
        rvn maven install org.junit.jupiter:junit-jupiter:5.10.0
    """
    api_url, slug, token = _resolve(profile, repo)
    try:
        repo_url = get_router(routing).maven_repo_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))

    settings_path: str | None = _write_settings(repo_url, token, "rvn") if token else None  # type: ignore[arg-type]
    cmd = [tools.mvn(), "dependency:get", f"-Dartifact={coords}", "-q"]
    if settings_path:
        cmd.extend(["--settings", settings_path])
    try:
        output.info(f"Fetching {coords} ...")
        subprocess.run(cmd, check=True)
        output.success(f"Fetched {coords}.")
    finally:
        if settings_path:
            Path(settings_path).unlink(missing_ok=True)


# ── sync ──────────────────────────────────────────────────────────────────────


@app.command("sync")
def maven_sync(
    profile: str | None = typer.Option(None, "--profile", "-p"),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    no_inject: bool = typer.Option(False, "--no-inject"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
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

    api_url, slug, token = _resolve(profile, repo)
    settings_path: str | None = None
    init_path: str | None = None

    try:
        if info.kind == "pom_xml":
            cmd = [tools.mvn(), "dependency:resolve", "-q"]
            if not no_inject and token:
                try:
                    repo_url = get_router(routing).maven_repo_url(api_url, slug)
                except NotImplementedError as exc:
                    output.fatal(str(exc))
                settings_path = _write_settings(repo_url, token)  # type: ignore[arg-type]
                cmd.extend(["--settings", settings_path])
        else:
            tool = "gradlew" if (cwd / "gradlew").exists() else "gradle"
            exe = f"./{tool}" if tool == "gradlew" else tool
            cmd = [exe, "dependencies", "--quiet"]
            if not no_inject and token:
                try:
                    repo_url = get_router(routing).maven_repo_url(api_url, slug)
                except NotImplementedError as exc:
                    output.fatal(str(exc))
                init_script = (
                    "allprojects {\n"
                    "  repositories { maven {\n"
                    f"    url '{repo_url}'\n"
                    f"    credentials {{ username '__token__'; password '{token}' }}\n"
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
def maven_add(
    coords: str = typer.Argument(
        ..., help="Maven coordinates: groupId:artifactId:version[:scope]."
    ),
    config: str = typer.Option(
        "implementation", help="Gradle configuration (e.g. testImplementation)."
    ),
    no_sync: bool = typer.Option(False, "--no-sync"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Add a Maven dependency to pom.xml or build.gradle.

    \b
        rvn maven add com.google.guava:guava:33.0.0-jre
        rvn maven add org.junit.jupiter:junit-jupiter:5.10.0:test
    """
    cwd = directory.resolve()
    info = mf.detect(cwd)
    if info is None or info.eco != "java":
        output.fatal("No Java manifest found.")

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

    parts = coords.split(":")
    if len(parts) < 3:
        return

    api_url, slug, token = _resolve(profile, repo)
    settings_path: str | None = None
    cmd = [tools.mvn(), "dependency:get", f"-Dartifact={coords}", "-q"]
    try:
        if token:
            try:
                repo_url = get_router(routing).maven_repo_url(api_url, slug)
            except NotImplementedError as exc:
                output.fatal(str(exc))
            settings_path = _write_settings(repo_url, token)  # type: ignore[arg-type]
            cmd.extend(["--settings", settings_path])
        output.info(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
    finally:
        if settings_path:
            Path(settings_path).unlink(missing_ok=True)


@app.command("remove")
def maven_remove(
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
        output.info("Run `rvn maven sync` to refresh the resolved dependency tree.")
    else:
        output.warn(f"'{coords}' not found in {info.path.name}")
        raise typer.Exit(1)


# ── deploy ────────────────────────────────────────────────────────────────────


@app.command("deploy")
def maven_deploy(
    jar: Path = typer.Argument(..., help="JAR (or WAR/POM) file to deploy."),
    group: str = typer.Option(..., "--group", "-g"),
    artifact: str = typer.Option(..., "--artifact", "-a"),
    version: str = typer.Option(..., "--version", "-v"),
    packaging: str = typer.Option("jar", "--packaging"),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Deploy a Maven artifact to the private registry.

    \b
        rvn maven deploy mylib.jar --group com.example --artifact mylib --version 1.0.0
    """
    api_url, slug, token = _require_token(profile, repo)
    try:
        upload_url = get_router(routing).maven_repo_url(api_url, slug)
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


# ── list / tree ───────────────────────────────────────────────────────────────


@app.command(
    "list",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def maven_list(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """List resolved project dependencies (mvn dependency:list)."""
    api_url, slug, token = _resolve(profile, repo)
    try:
        repo_url = get_router(routing).maven_repo_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    settings_path = _write_settings(repo_url, token, "rvn") if token else None  # type: ignore[arg-type]
    cmd = (
        [tools.mvn(), "dependency:list"]
        + (["--settings", settings_path] if settings_path else [])
        + ctx.args
    )
    try:
        subprocess.run(cmd, cwd=str(directory.resolve()), check=True)
    finally:
        if settings_path:
            Path(settings_path).unlink(missing_ok=True)


@app.command(
    "tree",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def maven_tree(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Print the dependency tree (mvn dependency:tree)."""
    api_url, slug, token = _resolve(profile, repo)
    try:
        repo_url = get_router(routing).maven_repo_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    settings_path = _write_settings(repo_url, token, "rvn") if token else None  # type: ignore[arg-type]
    cmd = (
        [tools.mvn(), "dependency:tree"]
        + (["--settings", settings_path] if settings_path else [])
        + ctx.args
    )
    try:
        subprocess.run(cmd, cwd=str(directory.resolve()), check=True)
    finally:
        if settings_path:
            Path(settings_path).unlink(missing_ok=True)


# ── yank ──────────────────────────────────────────────────────────────────────


@app.command("yank")
def maven_yank(
    coords: str = typer.Argument(..., help="Maven coordinates: groupId:artifactId:version."),
    reason: str | None = typer.Option(None, "--reason", "-m"),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Mark an artifact version as yanked via Ravenstash unified API.

    ✦ Unified feature — yank is not a native Maven protocol concept.
       A yanked version is hidden in the Ravenstash metadata layer.
       Standard Maven clients will NOT see the yank effect; only rvn-aware
       tooling respects it.

    \b
        rvn maven yank com.example:mylib:1.0.0
        rvn maven yank com.example:mylib:1.0.0 --reason "CVE-2024-12345"
    """
    parts = coords.split(":")
    if len(parts) < 3:
        output.fatal("Coords must be groupId:artifactId:version")
    package_name = f"{parts[0]}:{parts[1]}"
    version = parts[2]

    api_url, slug, token = _require_token(profile, repo)
    client = _api_client(api_url, token)
    body = {"reason": reason} if reason else None
    try:
        client.post(
            f"/webapp/repository/{slug}/packages/{package_name}/versions/{version}/yank",
            json=body,
        )
        output.success(f"Yanked {coords}.")
        if reason:
            output.info(f"Reason: {reason}")
    except ApiError as exc:
        output.fatal(str(exc))


# ── deprecate ─────────────────────────────────────────────────────────────────


@app.command("deprecate")
def maven_deprecate(
    coords: str = typer.Argument(..., help="Maven coordinates: groupId:artifactId:version."),
    message: str = typer.Argument(..., help="Deprecation message."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Mark an artifact version as deprecated via Ravenstash unified API.

    ✦ Unified feature — deprecation is not a native Maven protocol concept.
       Standard Maven clients will NOT see the deprecation; only rvn-aware
       tooling respects it.

    \b
        rvn maven deprecate com.example:mylib:1.0.0 "Use mylib:2.x instead"
    """
    parts = coords.split(":")
    if len(parts) < 3:
        output.fatal("Coords must be groupId:artifactId:version")
    package_name = f"{parts[0]}:{parts[1]}"
    version = parts[2]

    api_url, slug, token = _require_token(profile, repo)
    client = _api_client(api_url, token)
    try:
        client.post(
            f"/webapp/repository/{slug}/packages/{package_name}/versions/{version}/deprecate",
            json={"message": message},
        )
        output.success(f"Deprecated {coords}.")
        output.info(f"Message: {message}")
    except ApiError as exc:
        if exc.status_code == 404:
            output.fatal(
                "The deprecate endpoint requires a newer Ravenstash server.\n"
                "  Check for server updates at https://ravenstash.com/changelog"
            )
        output.fatal(str(exc))


# ── bump ──────────────────────────────────────────────────────────────────────


@app.command("bump")
def maven_bump(
    part: str = typer.Argument(..., help="major | minor | patch"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
) -> None:
    """Bump the pom.xml project version.

    Uses mvn versions:set when available, falls back to direct text replacement.

    \b
        rvn maven bump patch     # 1.2.3 → 1.2.4
        rvn maven bump minor     # 1.2.3 → 1.3.0
        rvn maven bump major     # 1.2.3 → 2.0.0
    """
    validate_bump_part(part)

    cwd = directory.resolve()
    pom = cwd / "pom.xml"
    if not pom.exists():
        output.fatal("No pom.xml found.  For Gradle, update the version in build.gradle manually.")

    content = pom.read_text()
    m = re.search(r"<version>([^<]+)</version>", content)
    if not m:
        output.fatal("Could not find <version>...</version> in pom.xml.")

    old_ver = m.group(1).strip()
    new_ver = bump_semver(old_ver, part)

    mvn_path = tools.resolve("mvn")
    if mvn_path:
        cmd = [
            mvn_path,
            "versions:set",
            f"-DnewVersion={new_ver}",
            "-DgenerateBackupPoms=false",
            "-q",
        ]
        output.info(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=str(cwd), check=False)
        if result.returncode != 0:
            output.fatal(f"mvn versions:set failed (exit {result.returncode}).")
    else:
        new_content = content[: m.start(1)] + new_ver + content[m.end(1) :]
        pom.write_text(new_content)

    output.success(f"Bumped version: {old_ver} → {new_ver}")


# ── version ───────────────────────────────────────────────────────────────────


@app.command("version")
def maven_version(
    bump: str | None = typer.Option(None, "--bump", help="major | minor | patch"),
    directory: Path = typer.Option(Path("."), "--directory", "-C"),
) -> None:
    """Display (or bump) the pom.xml project version.

    Uses mvn versions:set when available, falls back to direct text replacement.

    \b
        rvn maven version                  # print current version
        rvn maven version --bump patch     # 1.2.3 → 1.2.4
        rvn maven version --bump minor     # 1.2.3 → 1.3.0
        rvn maven version --bump major     # 1.2.3 → 2.0.0
    """
    cwd = directory.resolve()
    pom = cwd / "pom.xml"
    if not pom.exists():
        output.fatal("No pom.xml found.  For Gradle, update the version in build.gradle manually.")

    content = pom.read_text()
    m = re.search(r"<version>([^<]+)</version>", content)
    if not m:
        output.fatal("Could not find <version>...</version> in pom.xml.")

    current = m.group(1).strip()

    if bump is None:
        typer.echo(current)
        return

    validate_bump_part(bump)
    new_ver = bump_semver(current, bump)

    mvn_path = tools.resolve("mvn")
    if mvn_path:
        cmd = [
            mvn_path,
            "versions:set",
            f"-DnewVersion={new_ver}",
            "-DgenerateBackupPoms=false",
            "-q",
        ]
        output.info(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=str(cwd), check=False)
        if result.returncode != 0:
            output.fatal(f"mvn versions:set failed (exit {result.returncode}).")
    else:
        pom.write_text(content[: m.start(1)] + new_ver + content[m.end(1) :])

    output.success(f"Bumped version: {current} → {new_ver}")


# ── dist-tag ──────────────────────────────────────────────────────────────────
# Maven has no native dist-tag concept.  Tags live in the Ravenstash
# metadata layer and are used by rvn-aware tooling to resolve aliases
# like "stable", "release", or "beta".


@_tag_app.command("ls")
def maven_tag_ls(
    package: str = typer.Argument(..., help="Package name: groupId:artifactId."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """List distribution tags for an artifact.

    \b
        rvn maven dist-tag ls com.example:mylib
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
def maven_tag_add(
    coords: str = typer.Argument(..., help="Maven coordinates: groupId:artifactId:version."),
    tag: str = typer.Argument(..., help="Tag name, e.g. stable, release, beta."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Add or update a distribution tag.

    \b
        rvn maven dist-tag add com.example:mylib:1.0.0 stable
        rvn maven dist-tag add com.example:mylib:2.0.0-RC1 rc
    """
    parts = coords.split(":")
    if len(parts) < 3:
        output.fatal("Coords must be groupId:artifactId:version")
    package_name = f"{parts[0]}:{parts[1]}"
    version = parts[2]

    api_url, slug, token = _require_token(profile, repo)
    client = _api_client(api_url, token)
    try:
        client.post(
            f"/webapp/repository/{slug}/packages/{package_name}/dist-tags/{tag}",
            json={"version": version},
        )
        output.success(f"Tagged {coords} as '{tag}'.")
    except ApiError as exc:
        if exc.status_code == 404:
            output.fatal(
                "dist-tag management requires a newer Ravenstash server.\n"
                "  Check for server updates at https://ravenstash.com/changelog"
            )
        output.fatal(str(exc))


@_tag_app.command("rm")
def maven_tag_rm(
    package: str = typer.Argument(..., help="Package name: groupId:artifactId."),
    tag: str = typer.Argument(..., help="Tag to remove."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Remove a distribution tag.

    \b
        rvn maven dist-tag rm com.example:mylib stable
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
# Maven SNAPSHOT support is a native Maven protocol feature.
# Artifacts with a -SNAPSHOT version suffix can be overwritten on every deploy.


@_snap_app.command("deploy")
def maven_snap_deploy(
    jar: Path = typer.Argument(..., help="JAR file to deploy as a SNAPSHOT."),
    group: str = typer.Option(..., "--group", "-g"),
    artifact: str = typer.Option(..., "--artifact", "-a"),
    version: str = typer.Option(
        ..., "--version", "-v", help="Version without -SNAPSHOT suffix (added automatically)."
    ),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Deploy a Maven SNAPSHOT artifact to the private registry.

    The -SNAPSHOT suffix is appended automatically if not already present.

    \b
        rvn maven snapshot deploy mylib.jar \\
            --group com.example --artifact mylib --version 1.1.0
        # deploys as com.example:mylib:1.1.0-SNAPSHOT
    """
    api_url, slug, token = _require_token(profile, repo)
    snapshot_version = version if version.endswith("-SNAPSHOT") else f"{version}-SNAPSHOT"

    try:
        upload_url = get_router(routing).maven_repo_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))

    output.info(f"Deploying SNAPSHOT: {group}:{artifact}:{snapshot_version}")
    results = maven_reg.publish(
        upload_url=upload_url,
        token=token,
        group_id=group,
        artifact_id=artifact,
        version=snapshot_version,
        files=[jar],
    )
    any_fail = False
    for r in results:
        if r.ok:
            output.success(f"Deployed SNAPSHOT {r.filename}")
        else:
            output.error(f"Failed {r.filename}: {r.detail}")
            any_fail = True
    if any_fail:
        raise typer.Exit(1)


@_snap_app.command("ls")
def maven_snap_ls(
    package: str = typer.Argument(..., help="Package: groupId:artifactId."),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """List available SNAPSHOT versions for an artifact.

    \b
        rvn maven snapshot ls com.example:mylib
    """
    api_url, slug, token = _require_token(profile, repo)
    client = _api_client(api_url, token)
    try:
        data = client.get(f"/webapp/repository/{slug}/packages/{package}/").json()
    except ApiError as exc:
        output.fatal(str(exc))

    versions: list[str] = data.get("versions", []) if isinstance(data, dict) else []
    snapshots = [v for v in versions if "SNAPSHOT" in v.upper()]
    if not snapshots:
        output.info(f"No SNAPSHOT versions found for {package!r}.")
        return
    output.table(["SNAPSHOT version"], [[v] for v in snapshots], title=f"SNAPSHOTs: {package}")


# ── repo-url / settings-xml ──────────────────────────────────────────────────


@app.command("repo-url")
def maven_repo_url(
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Print the private Maven repository URL.

    \b
        rvn maven repo-url
    """
    api_url, slug, _ = _resolve(profile, repo)
    try:
        url = get_router(routing).maven_repo_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    typer.echo(url)


@app.command("settings-xml")
def maven_settings_xml(
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    server_id: str = typer.Option("rvn", "--server-id"),
    routing: RoutingMode = typer.Option("canonical", "--routing"),
) -> None:
    """Print a Maven settings.xml snippet for this registry.

    \b
        rvn maven settings-xml
        rvn maven settings-xml >> ~/.m2/settings.xml
    """
    api_url, slug, token = _resolve(profile, repo)
    try:
        repo_url = get_router(routing).maven_repo_url(api_url, slug)
    except NotImplementedError as exc:
        output.fatal(str(exc))
    typer.echo(maven_reg._build_settings_xml(repo_url, token or "<your-token>", server_id))
