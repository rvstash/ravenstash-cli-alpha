"""Confirmation shared by direct publishers and native launchers."""

from __future__ import annotations

import glob
import json
import re
import tarfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import typer
import yaml

from . import config, output
from .account.commands import display_name


if TYPE_CHECKING:
    from .artifacts.targets import RegistryContext


@dataclass(frozen=True)
class PublishItem:
    identity: str
    details: tuple[str, ...]
    file_count: int | None = None


def confirm_publish(
    repository: str,
    account: config.AccountContext,
    artifacts: list[PublishItem],
    *,
    yes: bool = False,
) -> None:
    if yes:
        return
    if output.is_json():
        output.fatal("Publishing requires confirmation. Pass --yes (native wrappers: --rvs-yes).")

    # Names are data, never terminal control sequences or Rich markup.
    def clean(value: str) -> str:
        return "".join(character if character.isprintable() else "?" for character in value)

    typer.echo(f"Publish to {clean(repository)} ({clean(display_name(account))})\n", err=True)
    for item in artifacts:
        typer.echo(clean(item.identity), err=True)
        for detail in item.details:
            typer.echo(f"  {clean(detail)}", err=True)
    typer.echo(err=True)
    if artifacts and all(item.file_count is not None for item in artifacts):
        count = sum(item.file_count or 0 for item in artifacts)
        question = "Publish this 1 file?" if count == 1 else f"Publish these {count} files?"
    else:
        question = "Publish these files/references?"
    typer.confirm(question, default=False, abort=True, err=True)


def confirm_context(
    context: RegistryContext, artifacts: list[PublishItem], *, yes: bool = False
) -> None:
    account = config.cached_account(context.profile_name, context.customer_id)
    if account is None:
        output.fatal("Cannot identify the publishing account.")
    confirm_publish(context.target.display_selector, account, artifacts, yes=yes)


def pypi_artifacts(files: list[Path]) -> list[PublishItem]:
    from .artifacts.registries.pypi import _read_metadata

    groups: dict[str, list[str]] = {}
    for path in files:
        meta = _read_metadata(path)
        name, version = meta.get("name"), meta.get("version")
        if isinstance(name, str) and isinstance(version, str):
            identity = f"PyPI {re.sub(r'[-_.]+', '-', name).lower()}=={version}"
        else:
            identity = "PyPI (package/version unavailable)"
        groups.setdefault(identity, []).append(path.name)
    return [PublishItem(identity, tuple(paths), len(paths)) for identity, paths in groups.items()]


def npm_artifact(path: Path, *, tag: str = "latest") -> PublishItem:
    try:
        if path.is_file():
            with tarfile.open(path, "r:gz") as archive:
                member = archive.getmember("package/package.json")
                if not member.isfile() or member.size > 1024 * 1024:
                    raise ValueError("Invalid package metadata")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("Missing package metadata")
                package = json.loads(stream.read())
        else:
            package = json.loads((path / "package.json").read_text())
        name, version = package["name"], package["version"]
        filename = f"{name.lstrip('@').replace('/', '-')}-{version}.tgz"
        source = str(path) if path.is_file() else f"{filename} (to be packed from {path})"
        return PublishItem(
            f"npm {name}@{version}", (source, f"npm tag: {tag}"), 1 if path.is_file() else None
        )
    except OSError, ValueError, KeyError, TypeError, AttributeError, tarfile.TarError:
        return PublishItem(
            "npm (package/version unavailable)",
            (f"Package selected from {path}", f"npm tag: {tag}"),
        )


def maven_artifact(group: str, artifact: str, version: str, files: list[str]) -> PublishItem:
    return PublishItem(f"Maven {group}:{artifact}:{version}", tuple(files), len(files))


def _option(argv: list[str], *names: str) -> str | None:
    for index, argument in enumerate(argv):
        for name in names:
            if argument.startswith(name + "="):
                return argument[len(name) + 1 :]
            if argument == name and index + 1 < len(argv):
                return argv[index + 1]
    return None


def native_artifacts(tool: str, argv: list[str]) -> list[PublishItem]:
    if tool == "npm":
        index = argv.index("publish") if "publish" in argv else -1
        candidate = argv[index + 1] if index >= 0 and index + 1 < len(argv) else "."
        if candidate.startswith("-"):
            return [
                PublishItem(
                    "npm publish",
                    (
                        "Package selection and tarball are resolved by npm.",
                        f"npm tag: {_option(argv, '--tag') or 'resolved by npm'}",
                    ),
                )
            ]
        if any(
            arg in {"--workspace", "-w", "--workspaces", "--prefix"}
            or arg.startswith(("--workspace=", "--prefix="))
            for arg in argv
        ):
            return [
                PublishItem(
                    "npm workspace/project publish",
                    ("Package selection and tarballs are resolved by npm.",),
                )
            ]
        return [
            npm_artifact(
                Path(candidate if not candidate.startswith("-") else "."),
                tag=_option(argv, "--tag") or "resolved by npm",
            )
        ]
    if tool == "mvn":
        props = {
            arg[2:].partition("=")[0]: arg.partition("=")[2]
            for arg in argv
            if arg.startswith("-D") and "=" in arg
        }
        pom = Path(props.get("pomFile") or _option(argv, "-f", "--file") or "pom.xml")
        if pom.is_dir():
            pom /= "pom.xml"
        try:
            root = ET.parse(pom).getroot()

            def field(name: str) -> str:
                return (
                    root.findtext(f"{{*}}{name}")
                    or root.findtext(f"{{*}}parent/{{*}}{name}")
                    or "?"
                )

            group, artifact, version = (
                props.get(key) or field(key) for key in ("groupId", "artifactId", "version")
            )
        except OSError, ET.ParseError:
            group, artifact, version = (
                props.get(key, "?") for key in ("groupId", "artifactId", "version")
            )
        files = [props[key] for key in ("file", "pomFile") if props.get(key)]
        files.extend(value for value in props.get("files", "").split(",") if value)
        if files and props.get("file"):
            return [
                PublishItem(
                    f"Maven {group}:{artifact}:{version}",
                    (*files, "Generated POM/checksum files are resolved by Maven."),
                )
            ]
        return [
            PublishItem(
                f"Maven {group}:{artifact}:{version}",
                (
                    f"Project: {pom}",
                    "Build output, modules and attached artifacts are resolved by Maven.",
                ),
            )
        ]
    command = "publish" if tool == "uv" else "upload"
    files: list[str] = []
    selection_known = command in argv
    if any(
        arg in {"--directory", "--project"} or arg.startswith(("--directory=", "--project="))
        for arg in argv
    ):
        selection_known = False
    remaining = argv[argv.index(command) + 1 :] if selection_known else []
    value_options = {
        "--repository",
        "-r",
        "--repository-url",
        "--username",
        "-u",
        "--password",
        "-p",
        "--config-file",
        "--cert",
        "--client-cert",
        "--publish-url",
        "--index",
        "--token",
        "--check-url",
    }
    switches = {
        "--skip-existing",
        "--non-interactive",
        "--verbose",
        "--disable-progress-bar",
        "--no-progress",
        "--trusted-publishing=never",
    }
    skip = False
    for arg in remaining:
        if skip:
            skip = False
        elif arg in value_options:
            skip = True
        elif arg in switches or any(arg.startswith(option + "=") for option in value_options):
            continue
        elif arg.startswith("-"):
            selection_known = False
        else:
            files.append(arg)
    if not files and selection_known and tool == "uv":
        files = [
            str(path)
            for path in sorted(Path("dist").glob("*"))
            if path.name.endswith((".whl", ".tar.gz")) and path.is_file()
        ]
    if files and selection_known:
        expanded = [
            Path(match) for pattern in files for match in (sorted(glob.glob(pattern)) or [pattern])
        ]
        return pypi_artifacts(expanded)
    return [
        PublishItem(
            "PyPI distributions",
            ("Files are selected by the native tool (normally dist/*.whl and dist/*.tar.gz).",),
        )
    ]


def oci_artifacts(tool: str, argv: list[str], registry_host: str) -> list[PublishItem]:
    references = [arg for arg in argv if registry_host + "/" in arg and not arg.startswith("-")]
    for argument in argv:
        if argument.startswith(("--tag=", "-t=")):
            reference = argument.partition("=")[2]
            if registry_host + "/" in reference and reference not in references:
                references.append(reference)
    if tool == "helm" and "push" in argv:
        index = argv.index("push")
        if len(argv) > index + 2 and not argv[index + 1].startswith("-"):
            path, destination = Path(argv[index + 1]), argv[index + 2].rstrip("/")
            try:
                if not destination.startswith("oci://"):
                    raise ValueError("Chart destination is not an OCI reference")
                with tarfile.open(path, "r:gz") as archive:
                    candidates = [
                        member
                        for member in archive
                        if member.name.count("/") == 1 and member.name.endswith("/Chart.yaml")
                    ]
                    if (
                        len(candidates) != 1
                        or not candidates[0].isfile()
                        or candidates[0].size > 1024 * 1024
                    ):
                        raise ValueError("Invalid chart metadata")
                    stream = archive.extractfile(candidates[0])
                    if stream is None:
                        raise ValueError("Missing chart metadata")
                    chart = yaml.safe_load(stream.read())
                name, version = chart["name"], str(chart["version"])
                if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", name):
                    raise ValueError("Invalid chart name")
                if not re.fullmatch(
                    r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", version
                ):
                    raise ValueError("Invalid chart version")
                reference = f"{destination}/{name}:{version.replace('+', '_')}"
                return [PublishItem(f"Helm {reference}", (str(path),), 1)]
            except OSError, ValueError, KeyError, TypeError, tarfile.TarError, yaml.YAMLError:
                return [
                    PublishItem(
                        "Helm (chart identity unavailable)",
                        (
                            str(path),
                            f"Destination: {destination}; chart name/tag resolved by Helm.",
                        ),
                    )
                ]
    platform = _option(argv, "--platform")
    details = (f"Platforms: {platform}",) if platform else ()
    if tool == "oras":
        details += tuple(
            arg for arg in argv if not arg.startswith("-") and Path(arg.split(":", 1)[0]).is_file()
        )
    if references:
        label = "Container" if tool == "docker" else "OCI"
        return [PublishItem(f"{label} {reference}", details) for reference in references]
    return [PublishItem("OCI publish", ("References are resolved by the native tool.",))]
