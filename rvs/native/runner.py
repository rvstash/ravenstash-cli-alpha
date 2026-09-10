"""Credential-aware native package-manager launchers.

These wrappers never persist Ravenstash credentials into package-manager config
files. They require a selected target, preserve additional native sources, and inject
short-lived credentials for the child process without editing lockfiles.
"""

from __future__ import annotations

import json
import netrc
import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse, urlsplit

import typer

from .. import config as cfg_mod
from .. import output
from ..account.commands import resolve_account
from ..artifacts.routing import (
    CanonicalRouter,
    native_base_url,
    npm_auth_token_key,
)
from ..artifacts.targets import registry_context
from ..publishing import PublishItem, confirm_context, native_artifacts
from ..runtime import tools
from ..subprocesses import child_environment


if TYPE_CHECKING:
    from collections.abc import Mapping


NativeTool = Literal["pip", "uv", "twine", "npm", "mvn"]
RegistryKind = Literal["pypi", "npm", "maven"]
PackageOperation = Literal["download", "upload"]
ConfigPolicy = Literal["respect", "override", "isolate"]

POLICIES: tuple[ConfigPolicy, ...] = ("respect", "override", "isolate")

_ROUTER = CanonicalRouter()
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")


@dataclass(frozen=True)
class NativeOptions:
    yes: bool = False
    profile: str | None = None
    target: str | None = None
    account: str | None = None
    customer_id: str | None = None
    native_config: ConfigPolicy = "respect"


@dataclass(frozen=True)
class RegistryRoute:
    kind: RegistryKind
    read_base_url: str
    push_base_url: str | None
    namespace_unique_ref: str
    repository_unique_ref: str
    package_token: str = field(repr=False)

    @property
    def pypi_index_url(self) -> str:
        return _ROUTER.pypi_index_url(
            self.read_base_url,
            self.namespace_unique_ref,
            self.repository_unique_ref,
        )

    @property
    def pypi_upload_url(self) -> str:
        if self.push_base_url is None:
            output.fatal("The selected private mirror is read-only.")
        return _ROUTER.pypi_upload_url(
            self.push_base_url,
            self.namespace_unique_ref,
            self.repository_unique_ref,
        )

    @property
    def npm_registry_url(self) -> str:
        return _ROUTER.npm_registry_url(
            self.read_base_url,
            self.namespace_unique_ref,
            self.repository_unique_ref,
        )

    @property
    def npm_upload_registry_url(self) -> str:
        if self.push_base_url is None:
            output.fatal("The selected private mirror is read-only.")
        return _ROUTER.npm_upload_registry_url(
            self.push_base_url,
            self.namespace_unique_ref,
            self.repository_unique_ref,
        )

    @property
    def maven_repo_url(self) -> str:
        return _ROUTER.maven_repo_url(
            self.read_base_url,
            self.namespace_unique_ref,
            self.repository_unique_ref,
        )

    @property
    def maven_upload_url(self) -> str:
        if self.push_base_url is None:
            output.fatal("The selected private mirror is read-only.")
        return _ROUTER.maven_upload_url(
            self.push_base_url,
            self.namespace_unique_ref,
            self.repository_unique_ref,
        )


@dataclass
class ExecutionPlan:
    cmd: list[str]
    env: dict[str, str]


def normalize_policy(value: str) -> ConfigPolicy:
    policy = value.strip().lower()
    if policy not in POLICIES:
        joined = ", ".join(POLICIES)
        output.fatal(f"Unknown --rvs-native-config '{value}'. Use one of: {joined}.")
    return policy  # type: ignore[return-value]


def run(tool: NativeTool, argv: list[str], options: NativeOptions) -> None:
    """Run *tool* with ephemeral Ravenstash credential injection."""
    with tempfile.TemporaryDirectory(prefix="rvs-native-") as temp_dir:
        plan = _build_plan(tool, argv, options, Path(temp_dir))
        result = subprocess.run(plan.cmd, env=plan.env, check=False)
        code = getattr(result, "returncode", 0)
        if code:
            raise typer.Exit(code)


def _build_plan(
    tool: NativeTool,
    argv: list[str],
    options: NativeOptions,
    temp_dir: Path,
) -> ExecutionPlan:
    env = child_environment()
    command_prefix = _command_prefix_for(tool)
    cmd = [*command_prefix, *argv]
    native_arg_start = len(command_prefix)
    # Help/version do not resolve packages and need no account or target.
    if argv in (["--version"], ["-V"], ["--help"], ["-h"], ["help"]):
        return ExecutionPlan(cmd=cmd, env=env)
    kind = _kind_for_tool(tool)
    customer_id = _selected_customer_id(options)
    saved = cfg_mod.selected_artifact_target(options.profile, customer_id)
    legacy = cfg_mod.load().registry_defaults(kind, options.profile)
    if not options.target and saved is None and not legacy.default_repo:
        output.fatal(
            "No Ravenstash target is selected. Run `rvs art select` or pass --rvs-target. "
            "Use the native tool directly for its default registries."
        )
    operations = _operations_for(tool, argv)
    # Never infer a target from native defaults or run an unconfigured client.
    # registry_context also supports explicitly selected legacy defaults.
    route = _resolve_route(
        _kind_for_tool(tool),
        options,
        operations,
        artifacts=native_artifacts(tool, argv) if _is_publishing(tool, argv) else None,
    )
    _inject_override(
        tool,
        cmd,
        native_arg_start,
        env,
        route,
        route.package_token,
        temp_dir,
        isolate=options.native_config == "isolate",
    )
    from .sources import warn_additional_sources

    warn_additional_sources(tool, argv, cmd[native_arg_start:], env, route)
    return ExecutionPlan(cmd=cmd, env=env)


def _command_prefix_for(tool: NativeTool) -> list[str]:
    match tool:
        case "pip":
            return tools.pip_cmd()
        case "npm":
            return [tools.npm()]
        case "uv":
            return [tools.require("uv", install_kind="system")]
        case "twine":
            return [tools.require("twine", install_kind="system")]
        case "mvn":
            return [tools.require("mvn", install_kind="system")]


def _kind_for_tool(tool: NativeTool) -> RegistryKind:
    match tool:
        case "pip" | "uv" | "twine":
            return "pypi"
        case "npm":
            return "npm"
        case "mvn":
            return "maven"


def _resolve_route(
    kind: RegistryKind,
    options: NativeOptions,
    operations: tuple[PackageOperation, ...],
    artifacts: list[PublishItem] | None = None,
) -> RegistryRoute:
    context = registry_context(
        kind=kind,
        target=options.target,
        repo=None,
        profile=options.profile,
        customer_id=_selected_customer_id(options),
        operations=operations,
    )
    if artifacts is not None:
        confirm_context(context, artifacts, yes=options.yes)
    return RegistryRoute(
        kind=kind,
        read_base_url=context.read_base_url,
        push_base_url=context.push_base_url,
        namespace_unique_ref=context.namespace_reference,
        repository_unique_ref=context.repository_reference,
        package_token=context.token,
    )


def _selected_customer_id(options: NativeOptions) -> str | None:
    if options.customer_id:
        return options.customer_id
    if options.account:
        return str(resolve_account(options.account, options.profile)["customer_id"])
    profile_name = options.profile or cfg_mod.current_profile_name()
    return cfg_mod.current_customer_id(profile_name)


def _is_publishing(tool: NativeTool, argv: list[str]) -> bool:
    return (
        (tool == "twine" and "upload" in argv)
        or (tool in {"uv", "npm"} and "publish" in argv)
        or (tool == "mvn" and _maven_is_upload(argv))
    )


def _operations_for(
    tool: NativeTool,
    argv: list[str],
) -> tuple[PackageOperation, ...]:
    if tool == "twine":
        return ("upload",)
    if tool == "uv" and any(arg == "publish" for arg in argv if not arg.startswith("-")):
        return ("upload",)
    if tool == "npm" and _npm_is_publish(argv):
        return ("upload",)
    if tool == "npm" and _npm_is_mutation(argv):
        return ("download", "upload")
    if tool == "mvn" and _maven_is_upload(argv):
        return ("download", "upload")
    return ("download",)


def _extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in _URL_RE.finditer(text):
        urls.append(match.group(0).rstrip(".,);]"))
    return urls


def _same_origin(left: str, right: str) -> bool:
    first = urlsplit(left)
    second = urlsplit(right)
    try:
        return (
            first.scheme.lower(),
            first.hostname.rstrip(".").lower() if first.hostname else None,
            first.port or (443 if first.scheme.lower() == "https" else 80),
        ) == (
            second.scheme.lower(),
            second.hostname.rstrip(".").lower() if second.hostname else None,
            second.port or (443 if second.scheme.lower() == "https" else 80),
        )
    except ValueError:
        return False


def _ravenstash_url_kind(
    url: str,
    *,
    native_registries: cfg_mod.NativeRegistryEndpoints,
) -> RegistryKind | None:
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    for kind in ("pypi", "npm", "maven"):
        endpoints = native_registries.package(kind)
        for service_url, surface in (
            (endpoints.read_base_url, "private"),
            (endpoints.push_base_url, "private"),
            (endpoints.mirror_base_url, "mirror"),
        ):
            base = native_base_url(service_url)
            if not _same_origin(url, base):
                continue
            base_parts = [part for part in urlparse(base).path.split("/") if part]
            path_parts = [part for part in parsed.path.split("/") if part]
            if path_parts[: len(base_parts)] != base_parts:
                continue
            route_parts = path_parts[len(base_parts) :]
            if (surface == "private" and _valid_private_registry_route(route_parts)) or (
                surface == "mirror" and _valid_mirror_registry_route(route_parts)
            ):
                return kind  # type: ignore[return-value]
    return None


def _valid_private_registry_route(path_parts: list[str]) -> bool:
    return len(path_parts) >= 2 and path_parts[0] not in {"o", "c"} and bool(path_parts[1])


def _valid_mirror_registry_route(path_parts: list[str]) -> bool:
    return len(path_parts) >= 2 and path_parts[0] in {"o", "c"} and bool(path_parts[1])


def _relevant_env_values(tool: NativeTool, env: dict[str, str]) -> list[str]:
    prefixes = {
        "pip": ("PIP_",),
        "uv": ("UV_", "NETRC"),
        "twine": ("TWINE_",),
        "npm": ("NPM_CONFIG_", "npm_config_"),
        "mvn": ("MAVEN_",),
    }[tool]
    return [
        value for key, value in env.items() if key.startswith(prefixes) and isinstance(value, str)
    ]


def _candidate_config_files(
    tool: NativeTool,
    argv: list[str],
    env: Mapping[str, str],
) -> list[Path]:
    candidates: list[Path] = []
    match tool:
        case "pip":
            if env.get("PIP_CONFIG_FILE"):
                candidates.append(Path(env["PIP_CONFIG_FILE"]).expanduser())
            if env.get("VIRTUAL_ENV"):
                candidates.append(Path(env["VIRTUAL_ENV"]) / "pip.conf")
            candidates.extend(
                [
                    Path.cwd() / "pip.conf",
                    Path.home() / ".config/pip/pip.conf",
                    Path.home() / ".pip/pip.conf",
                    Path("/etc/pip.conf"),
                ]
            )
        case "uv":
            candidates.extend(_nearest_named_files(("uv.toml", "pyproject.toml")))
            if env.get("UV_CONFIG_FILE"):
                candidates.append(Path(env["UV_CONFIG_FILE"]).expanduser())
            candidates.append(Path.home() / ".config/uv/uv.toml")
        case "twine":
            config_file = _arg_value(argv, "--config-file")
            if config_file:
                candidates.append(Path(config_file).expanduser())
            candidates.append(Path.home() / ".pypirc")
        case "npm":
            user_config = env.get("NPM_CONFIG_USERCONFIG") or env.get("npm_config_userconfig")
            global_config = env.get("NPM_CONFIG_GLOBALCONFIG") or env.get("npm_config_globalconfig")
            candidates.extend(_nearest_named_files((".npmrc",)))
            if user_config:
                candidates.append(Path(user_config).expanduser())
            candidates.append(Path.home() / ".npmrc")
            if global_config:
                candidates.append(Path(global_config).expanduser())
        case "mvn":
            settings_file = _maven_settings_arg(argv)
            if settings_file:
                candidates.append(Path(settings_file).expanduser())
            candidates.append(Path.home() / ".m2/settings.xml")
            candidates.extend(_nearest_named_files(("pom.xml",)))
    return [path for path in candidates if path.exists() and path.is_file()]


def _nearest_named_files(names: tuple[str, ...]) -> list[Path]:
    found: list[Path] = []
    for directory in (Path.cwd(), *Path.cwd().parents):
        for name in names:
            candidate = directory / name
            if candidate.exists() and candidate.is_file():
                found.append(candidate)
    return found


def _arg_value(argv: list[str], option: str, short: str | None = None) -> str | None:
    for index, arg in enumerate(argv):
        if arg == option and index + 1 < len(argv):
            return argv[index + 1]
        if short and arg == short and index + 1 < len(argv):
            return argv[index + 1]
        prefix = f"{option}="
        if arg.startswith(prefix):
            return arg.removeprefix(prefix)
    return None


def _inject_override(
    tool: NativeTool,
    cmd: list[str],
    native_arg_start: int,
    env: dict[str, str],
    route: RegistryRoute,
    token: str,
    temp_dir: Path,
    *,
    isolate: bool,
) -> None:
    match tool:
        case "pip":
            _inject_pip_override(
                cmd,
                native_arg_start,
                env,
                route,
                token,
                temp_dir,
                isolate=isolate,
            )
        case "uv":
            _inject_uv_override(
                cmd,
                native_arg_start,
                env,
                route,
                token,
                temp_dir,
                isolate=isolate,
            )
        case "twine":
            _inject_twine_override(cmd, native_arg_start, env, route, token, isolate=isolate)
        case "npm":
            _inject_npm_override(
                cmd,
                native_arg_start,
                env,
                route,
                token,
                isolate=isolate,
                temp_dir=temp_dir,
            )
        case "mvn":
            maven_args = cmd[native_arg_start:]
            urls = [route.maven_repo_url]
            if _maven_is_upload(maven_args):
                urls.append(route.maven_upload_url)
            settings_path = _write_maven_settings(
                urls=urls,
                token=token,
                temp_dir=temp_dir,
                argv=cmd[native_arg_start:],
                isolate=isolate,
                route=route,
            )
            _replace_maven_settings_arg(cmd, settings_path, native_arg_start)
            if _maven_has_goal(maven_args, "deploy"):
                cmd.append(
                    f"-DaltDeploymentRepository=rvs-private::default::{route.maven_upload_url}"
                )
            if _maven_has_goal(maven_args, "deploy-file"):
                cmd.extend(
                    [
                        "-DrepositoryId=rvs-private",
                        f"-Durl={route.maven_upload_url}",
                    ]
                )


def _inject_pip_override(
    cmd: list[str],
    native_arg_start: int,
    env: dict[str, str],
    route: RegistryRoute,
    token: str,
    temp_dir: Path,
    *,
    isolate: bool,
) -> None:
    url = route.pypi_index_url
    _write_netrc(env, [url], token, temp_dir)
    env["PIP_INDEX_URL"] = url
    if isolate:
        env["PIP_CONFIG_FILE"] = os.devnull
    _insert_pip_index_arg(cmd, native_arg_start, url)


def _insert_pip_index_arg(cmd: list[str], native_arg_start: int, url: str) -> None:
    if len(cmd) <= native_arg_start:
        return
    subcommand = cmd[native_arg_start]
    if subcommand not in {"install", "download", "wheel", "index", "lock"}:
        return
    _remove_value_options(cmd, {"--index-url", "-i"}, native_arg_start)
    cmd[native_arg_start + 1 : native_arg_start + 1] = ["--index-url", url]


def _inject_uv_override(
    cmd: list[str],
    native_arg_start: int,
    env: dict[str, str],
    route: RegistryRoute,
    token: str,
    temp_dir: Path,
    *,
    isolate: bool,
) -> None:
    publishing = _is_publishing("uv", cmd[native_arg_start:])
    urls = [route.pypi_index_url]
    if publishing:
        urls.append(route.pypi_upload_url)
    _write_netrc(env, urls, token, temp_dir)
    _remove_value_options(cmd, {"--default-index", "--index-url"}, native_arg_start)
    env["UV_DEFAULT_INDEX"] = route.pypi_index_url
    env["UV_INDEX_URL"] = route.pypi_index_url
    if publishing:
        _remove_value_options(cmd, {"--publish-url", "--index"}, native_arg_start)
        cmd.extend(["--publish-url", route.pypi_upload_url])
        env["UV_PUBLISH_URL"] = route.pypi_upload_url
        env["UV_PUBLISH_USERNAME"] = "__token__"
        env["UV_PUBLISH_PASSWORD"] = token
    if isolate:
        env["UV_NO_CONFIG"] = "1"
        env["UV_NO_ENV_FILE"] = "1"


def _inject_twine_override(
    cmd: list[str],
    native_arg_start: int,
    env: dict[str, str],
    route: RegistryRoute,
    token: str,
    *,
    isolate: bool,
) -> None:
    del isolate
    _remove_value_options(
        cmd,
        {"--repository-url", "--username", "-u", "--password", "-p"},
        native_arg_start,
    )
    env["TWINE_REPOSITORY_URL"] = route.pypi_upload_url
    env["TWINE_USERNAME"] = "__token__"
    env["TWINE_PASSWORD"] = token
    env.setdefault("TWINE_NON_INTERACTIVE", "1")


def _inject_npm_override(
    cmd: list[str],
    native_arg_start: int,
    env: dict[str, str],
    route: RegistryRoute,
    token: str,
    *,
    isolate: bool,
    temp_dir: Path,
) -> None:
    registry_url = (
        route.npm_upload_registry_url
        if _npm_is_publish(cmd[native_arg_start:]) or _npm_is_mutation(cmd[native_arg_start:])
        else route.npm_registry_url
    )
    _replace_npm_registry_arg(cmd, native_arg_start, registry_url)
    env["NPM_CONFIG_REGISTRY"] = registry_url
    _inject_npm_auth(env, [registry_url], token)
    if isolate:
        user_npmrc = temp_dir / "user.npmrc"
        global_npmrc = temp_dir / "global.npmrc"
        user_npmrc.write_text("", encoding="utf-8")
        global_npmrc.write_text("", encoding="utf-8")
        env["NPM_CONFIG_USERCONFIG"] = str(user_npmrc)
        env["NPM_CONFIG_GLOBALCONFIG"] = str(global_npmrc)


def _npm_is_publish(argv: list[str]) -> bool:
    return any(arg == "publish" for arg in argv if not arg.startswith("-"))


def _npm_is_mutation(argv: list[str]) -> bool:
    positional = [arg for arg in argv if not arg.startswith("-")]
    if any(arg in {"unpublish", "deprecate", "tag"} for arg in positional):
        return True
    # Ravenstash's native dist-tag endpoint is served by Publisher for both
    # reads and mutations. Route ``ls`` there as well and request the combined
    # capability expected by that authenticated endpoint.
    return "dist-tag" in positional


def _replace_npm_registry_arg(cmd: list[str], native_arg_start: int, registry_url: str) -> None:
    _remove_value_options(cmd, {"--registry"}, native_arg_start)
    if len(cmd) > native_arg_start and not cmd[native_arg_start].startswith("-"):
        insert_at = native_arg_start + 1
        cmd[insert_at:insert_at] = ["--registry", registry_url]
    else:
        cmd.append("--registry")
        cmd.append(registry_url)


def _remove_value_options(
    cmd: list[str],
    option_names: set[str],
    native_arg_start: int,
) -> None:
    cleaned = cmd[:native_arg_start]
    skip_next = False
    for arg in cmd[native_arg_start:]:
        if skip_next:
            skip_next = False
            continue
        if arg in option_names:
            skip_next = True
            continue
        if any(arg.startswith(f"{option}=") for option in option_names):
            continue
        cleaned.append(arg)
    cmd[:] = cleaned


def _inject_npm_auth(env: dict[str, str], urls: list[str], token: str) -> None:
    for url in urls:
        auth_key = npm_auth_token_key(url)
        env[f"NPM_CONFIG_{auth_key}"] = token


def _write_netrc(
    env: dict[str, str],
    urls: list[str],
    token: str,
    temp_dir: Path,
) -> None:
    hosts = sorted({host for url in urls if (host := urlparse(url).hostname) is not None})
    if not hosts:
        return
    netrc_path = temp_dir / "netrc"
    original = Path(env.get("NETRC", str(Path.home() / ".netrc"))).expanduser()
    preserved = ""
    if original.is_file():
        try:
            existing = netrc.netrc(str(original))
        except OSError, netrc.NetrcParseError:
            output.fatal("Cannot read native netrc credentials; repair the file before retrying.")
        for host in hosts:
            existing.hosts.pop(host, None)
        for host, (login, account, password) in existing.hosts.items():
            entry = "default" if host == "default" else f"machine {json.dumps(host)}"
            entry += f" login {json.dumps(login or '')}"
            if account:
                entry += f" account {json.dumps(account)}"
            entry += f" password {json.dumps(password or '')}\n"
            preserved += entry
    lines = [f"machine {host} login __token__ password {token}" for host in hosts]
    netrc_path.write_text(preserved + "\n".join(lines) + "\n", encoding="utf-8")
    netrc_path.chmod(0o600)
    env["NETRC"] = str(netrc_path)


def inject_pip_auth(
    env: dict[str, str],
    urls: list[str],
    token: str,
    temp_dir: Path,
) -> None:
    """Inject one ephemeral capability for the duration of a pip command."""
    _write_netrc(env, urls, token, temp_dir)


def _write_maven_settings(
    *,
    urls: list[str],
    token: str,
    temp_dir: Path,
    argv: list[str],
    isolate: bool,
    route: RegistryRoute | None,
) -> Path:
    base_settings = None if isolate else _maven_settings_arg(argv)
    base_path = (
        Path(base_settings).expanduser() if base_settings else Path.home() / ".m2/settings.xml"
    )
    root = _load_maven_settings(base_path) if not isolate else ET.Element("settings")
    server_ids = set() if route is not None else _maven_server_ids_for_urls(urls, argv)
    if route is not None:
        server_ids.add("rvs-private")
        _ensure_maven_profile(root, route, isolate=isolate)
    if not server_ids:
        server_ids.add("rvs-private")
    servers = _ensure_xml_child(root, "servers")
    if route is not None:
        for element in root.iter():
            if _local_name(element.tag) in {"repository", "pluginRepository", "snapshotRepository"}:
                if (
                    _child_text(element, "id") == "rvs-private"
                    and _child_text(element, "url") not in urls
                ):
                    output.fatal(
                        "Native Maven settings use reserved repository ID rvs-private for another URL."
                    )
    for server_id in sorted(server_ids):
        _upsert_maven_server(servers, server_id, token)

    settings_path = temp_dir / "settings.xml"
    ET.ElementTree(root).write(settings_path, encoding="utf-8", xml_declaration=True)
    settings_path.chmod(0o600)
    return settings_path


def _load_maven_settings(path: Path) -> ET.Element:
    if path.exists() and path.is_file():
        try:
            return ET.parse(path).getroot()
        except ET.ParseError:
            pass
    return ET.Element("settings")


def _maven_server_ids_for_urls(urls: list[str], argv: list[str]) -> set[str]:
    ids: set[str] = set()
    for path in _candidate_config_files("mvn", argv, os.environ):
        if path.suffix.lower() != ".xml":
            continue
        try:
            root = ET.parse(path).getroot()
        except OSError, ET.ParseError:
            continue
        for element in root.iter():
            if _local_name(element.tag) not in {
                "repository",
                "pluginRepository",
                "snapshotRepository",
            }:
                continue
            repo_url = _child_text(element, "url")
            repo_id = _child_text(element, "id")
            if repo_id and repo_url and repo_url in urls:
                ids.add(repo_id)
    return ids


def _ensure_maven_profile(root: ET.Element, route: RegistryRoute, *, isolate: bool = False) -> None:
    mirrors = _ensure_xml_child(root, "mirrors")
    for existing in mirrors:
        if _child_text(existing, "id") == "rvs-private":
            if _child_text(existing, "url") != route.maven_repo_url:
                output.fatal(
                    "Native Maven settings use reserved mirror ID rvs-private for another URL."
                )
            continue
        pattern = _child_text(existing, "mirrorOf") or ""
        if pattern:
            output.warn(
                "Existing Maven mirrors are preserved for additional repositories; "
                "Central and the selected Ravenstash repository use the selected target."
            )
            # Exclude our repository and Central even from an existing exact match.
            remaining = [
                part.strip()
                for part in pattern.split(",")
                if part.strip() not in {"central", "rvs-private"}
            ]
            _ensure_xml_child(existing, "mirrorOf").text = ",".join(
                [*remaining, "!central", "!rvs-private"]
            )
    mirror = _find_child_with_text(mirrors, "mirror", "id", "rvs-private")
    if mirror is None:
        mirror = ET.SubElement(mirrors, "mirror")
        ET.SubElement(mirror, "id").text = "rvs-private"
    _ensure_xml_child(mirror, "url").text = route.maven_repo_url
    _ensure_xml_child(mirror, "mirrorOf").text = "*" if isolate else "central"

    profiles = _ensure_xml_child(root, "profiles")
    profile = _find_child_with_text(profiles, "profile", "id", "rvs")
    if profile is None:
        profile = ET.SubElement(profiles, "profile")
        ET.SubElement(profile, "id").text = "rvs"
    repositories = _ensure_xml_child(profile, "repositories")
    plugin_repositories = _ensure_xml_child(profile, "pluginRepositories")
    _upsert_maven_repository(repositories, "repository", route.maven_repo_url)
    _upsert_maven_repository(plugin_repositories, "pluginRepository", route.maven_repo_url)
    active_profiles = _ensure_xml_child(root, "activeProfiles")
    if _find_child_text(active_profiles, "activeProfile", "rvs") is None:
        ET.SubElement(active_profiles, "activeProfile").text = "rvs"


def _upsert_maven_repository(parent: ET.Element, tag: str, url: str) -> None:
    repo = _find_child_with_text(parent, tag, "id", "rvs-private")
    if repo is None:
        repo = ET.SubElement(parent, tag)
        ET.SubElement(repo, "id").text = "rvs-private"
    url_element = _ensure_xml_child(repo, "url")
    url_element.text = url


def _upsert_maven_server(servers: ET.Element, server_id: str, token: str) -> None:
    server = _find_child_with_text(servers, "server", "id", server_id)
    if server is None:
        server = ET.SubElement(servers, "server")
        ET.SubElement(server, "id").text = server_id
    username = _ensure_xml_child(server, "username")
    password = _ensure_xml_child(server, "password")
    username.text = "__token__"
    password.text = token


def _replace_maven_settings_arg(
    cmd: list[str],
    settings_path: Path,
    native_arg_start: int,
) -> None:
    cleaned: list[str] = cmd[:native_arg_start]
    skip_next = False
    for arg in cmd[native_arg_start:]:
        if skip_next:
            skip_next = False
            continue
        if arg in {"-s", "--settings"}:
            skip_next = True
            continue
        if arg.startswith("--settings="):
            continue
        cleaned.append(arg)
    cleaned[native_arg_start:native_arg_start] = ["--settings", str(settings_path)]
    cmd[:] = cleaned


def _maven_settings_arg(argv: list[str]) -> str | None:
    return _arg_value(argv, "--settings", "-s")


def _maven_has_goal(argv: list[str], goal: str) -> bool:
    return any(arg == goal or arg.endswith(f":{goal}") for arg in argv if not arg.startswith("-"))


def _maven_is_upload(argv: list[str]) -> bool:
    return _maven_has_goal(argv, "deploy") or _maven_has_goal(argv, "deploy-file")


def _ensure_xml_child(parent: ET.Element, tag: str) -> ET.Element:
    for child in parent:
        if _local_name(child.tag) == tag:
            return child
    return ET.SubElement(parent, tag)


def _find_child_with_text(
    parent: ET.Element,
    child_tag: str,
    grandchild_tag: str,
    value: str,
) -> ET.Element | None:
    for child in parent:
        if _local_name(child.tag) != child_tag:
            continue
        if _child_text(child, grandchild_tag) == value:
            return child
    return None


def _find_child_text(parent: ET.Element, tag: str, value: str) -> str | None:
    for child in parent:
        if _local_name(child.tag) == tag and (child.text or "").strip() == value:
            return child.text
    return None


def _child_text(parent: ET.Element, tag: str) -> str | None:
    for child in parent:
        if _local_name(child.tag) == tag:
            text = (child.text or "").strip()
            return text or None
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
