"""Credential-aware native package-manager launchers.

These wrappers never persist Ravenstash credentials into package-manager config
files. They read native config only to decide whether an invocation references a
Ravenstash registry, then inject short-lived credentials for the child process.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

import typer

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import output
from ..pkg.routing import CanonicalRouter
from ..runtime import tools


if TYPE_CHECKING:
    from collections.abc import Mapping


NativeTool = Literal["pip", "uv", "twine", "npm", "mvn"]
RegistryKind = Literal["pypi", "npm", "maven"]
ConfigPolicy = Literal["respect", "override", "isolate"]

POLICIES: tuple[ConfigPolicy, ...] = ("respect", "override", "isolate")

_ROUTER = CanonicalRouter()
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_RVS_URL_KINDS: dict[NativeTool, tuple[RegistryKind, ...]] = {
    "pip": ("pypi",),
    "uv": ("pypi",),
    "twine": ("pypi",),
    "npm": ("npm",),
    "mvn": ("maven",),
}


@dataclass(frozen=True)
class NativeOptions:
    profile: str | None = None
    repo: str | None = None
    customer_pid: str | None = None
    native_config: ConfigPolicy = "respect"


@dataclass(frozen=True)
class RegistryRoute:
    kind: RegistryKind
    pkg_download_url: str
    pkg_upload_url: str
    customer_pid: str
    repository_name: str

    @property
    def pypi_index_url(self) -> str:
        return _ROUTER.pypi_index_url(
            self.pkg_download_url, self.customer_pid, self.repository_name
        )

    @property
    def pypi_upload_url(self) -> str:
        return _ROUTER.pypi_upload_url(self.pkg_upload_url, self.customer_pid, self.repository_name)

    @property
    def npm_registry_url(self) -> str:
        return _ROUTER.npm_registry_url(
            self.pkg_download_url, self.customer_pid, self.repository_name
        )

    @property
    def npm_upload_registry_url(self) -> str:
        return _ROUTER.npm_upload_registry_url(
            self.pkg_upload_url,
            self.customer_pid,
            self.repository_name,
        )

    @property
    def maven_repo_url(self) -> str:
        return _ROUTER.maven_repo_url(
            self.pkg_download_url, self.customer_pid, self.repository_name
        )

    @property
    def maven_upload_url(self) -> str:
        return _ROUTER.maven_upload_url(
            self.pkg_upload_url, self.customer_pid, self.repository_name
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
    env = {**os.environ}
    command_prefix = _command_prefix_for(tool)
    cmd = [*command_prefix, *argv]
    native_arg_start = len(command_prefix)
    effective_policy = (
        "override" if options.repo and options.native_config == "respect" else options.native_config
    )

    if effective_policy == "respect":
        urls = _detected_ravenstash_urls(tool, argv, env)
        if not urls:
            return ExecutionPlan(cmd=cmd, env=env)
        token = _require_token(options.profile)
        _inject_for_detected_urls(tool, cmd, native_arg_start, env, urls, token, temp_dir)
        return ExecutionPlan(cmd=cmd, env=env)

    route = _resolve_route(_kind_for_tool(tool), options)
    token = _require_token(options.profile)
    _inject_override(
        tool,
        cmd,
        native_arg_start,
        env,
        route,
        token,
        temp_dir,
        isolate=effective_policy == "isolate",
    )
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


def _profile_name(profile: str | None) -> str:
    cfg = cfg_mod.load()
    return profile or cfg_mod.current_profile_name(cfg)


def _profile(profile: str | None) -> cfg_mod.ProfileConfig:
    cfg = cfg_mod.load()
    return cfg.active_profile(profile or cfg_mod.current_profile_name(cfg))


def _require_token(profile: str | None) -> str:
    token = auth_mod.get_token(_profile_name(profile))
    if not token:
        output.fatal("Not authenticated. Run `rvs auth login` or set RVS_TOKEN.")
    return token


def _split_repo_ref(repo_ref: str) -> tuple[str | None, str]:
    value = repo_ref.strip().strip("/")
    if not value:
        output.fatal("Repository name cannot be empty.")
    if "/" not in value:
        return None, value
    customer_pid, repository_name = value.split("/", 1)
    customer_pid = customer_pid.strip()
    repository_name = repository_name.strip().strip("/")
    if not customer_pid or not repository_name or "/" in repository_name:
        output.fatal(
            "Repository must be <repository-name> or <customer-public-id>/<repository-name>."
        )
    return customer_pid, repository_name


def _customer_public_id(profile: str | None, explicit_customer_pid: str | None) -> str:
    if explicit_customer_pid:
        return explicit_customer_pid
    env_customer_pid = os.environ.get("RVS_CUSTOMER_PID") or os.environ.get(
        "RVS_CUSTOMER_PUBLIC_ID"
    )
    if env_customer_pid:
        return env_customer_pid
    profile_cfg = _profile(profile)
    if not profile_cfg.customer_public_id:
        output.fatal(
            "No customer public ID is stored for this profile. "
            "Run `rvs auth login` again, pass --rvs-customer-pid, or pass "
            "--rvs-repo <customer-public-id>/<repository-name>."
        )
    return profile_cfg.customer_public_id


def _resolve_route(kind: RegistryKind, options: NativeOptions) -> RegistryRoute:
    cfg = cfg_mod.load()
    profile_name = options.profile or cfg_mod.current_profile_name(cfg)
    repo_ref = options.repo or cfg.registry_defaults(kind, profile_name).default_repo
    if not repo_ref:
        output.fatal(
            f"No {kind} package repository selected. Pass --rvs-repo or run "
            f"`rvs pkg repo set-default {kind} <repository-name>`."
        )
    repo_customer_pid, repository_name = _split_repo_ref(repo_ref)
    customer_pid = repo_customer_pid or _customer_public_id(options.profile, options.customer_pid)
    profile_cfg = _profile(options.profile)
    return RegistryRoute(
        kind=kind,
        pkg_download_url=profile_cfg.pkg_download_url,
        pkg_upload_url=profile_cfg.pkg_upload_url,
        customer_pid=customer_pid,
        repository_name=repository_name,
    )


def _detected_ravenstash_urls(
    tool: NativeTool,
    argv: list[str],
    env: dict[str, str],
) -> list[str]:
    candidate_texts: list[str] = [" ".join(argv)]
    candidate_texts.extend(_relevant_env_values(tool, env))
    for path in _candidate_config_files(tool, argv, env):
        try:
            candidate_texts.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue

    urls: list[str] = []
    seen: set[str] = set()
    allowed_kinds = _RVS_URL_KINDS[tool]
    for text in candidate_texts:
        for url in _extract_urls(text):
            if url in seen:
                continue
            kind = _ravenstash_url_kind(url)
            if kind in allowed_kinds:
                seen.add(url)
                urls.append(url)
    return urls


def _extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in _URL_RE.finditer(text):
        urls.append(match.group(0).rstrip(".,);]"))
    return urls


def _ravenstash_url_kind(url: str) -> RegistryKind | None:
    parsed = urlparse(url)
    path_parts = [part for part in parsed.path.split("/") if part]

    if len(path_parts) >= 4 and path_parts[0] == "native":
        kind = path_parts[1]
        if kind in {"pypi", "npm", "maven"}:
            return kind  # type: ignore[return-value]

    if len(path_parts) < 2 or parsed.hostname is None:
        return None
    host_parts = parsed.hostname.split(".")
    if len(host_parts) < 2:
        return None
    kind = host_parts[0]
    if kind not in {"pypi", "npm", "maven"}:
        return None
    if not (
        host_parts[1] == "pkg"
        or host_parts[1] == "push"
        or host_parts[1].startswith("pkg-")
        or host_parts[1].startswith("push-")
    ):
        return None
    return kind  # type: ignore[return-value]


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


def _inject_for_detected_urls(
    tool: NativeTool,
    cmd: list[str],
    native_arg_start: int,
    env: dict[str, str],
    urls: list[str],
    token: str,
    temp_dir: Path,
) -> None:
    match tool:
        case "npm":
            _inject_npm_auth(env, urls, token)
        case "twine":
            env["TWINE_USERNAME"] = "__token__"
            env["TWINE_PASSWORD"] = token
            env.setdefault("TWINE_NON_INTERACTIVE", "1")
        case "mvn":
            settings_path = _write_maven_settings(
                urls=urls,
                token=token,
                temp_dir=temp_dir,
                argv=cmd[native_arg_start:],
                isolate=False,
                route=None,
            )
            _replace_maven_settings_arg(cmd, settings_path, native_arg_start)
        case "pip" | "uv":
            _write_netrc(env, urls, token, temp_dir)


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
            settings_path = _write_maven_settings(
                urls=[route.maven_repo_url, route.maven_upload_url],
                token=token,
                temp_dir=temp_dir,
                argv=cmd[native_arg_start:],
                isolate=isolate,
                route=route,
            )
            _replace_maven_settings_arg(cmd, settings_path, native_arg_start)
            if _maven_has_goal(cmd[native_arg_start:], "deploy"):
                cmd.append(
                    f"-DaltDeploymentRepository=rvs-private::default::{route.maven_upload_url}"
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
    if subcommand not in {"install", "download", "wheel", "index"}:
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
    _write_netrc(env, [route.pypi_index_url, route.pypi_upload_url], token, temp_dir)
    _remove_value_options(
        cmd,
        {"--default-index", "--index-url", "--publish-url"},
        native_arg_start,
    )
    env["UV_DEFAULT_INDEX"] = route.pypi_index_url
    env["UV_INDEX_URL"] = route.pypi_index_url
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
        if _npm_is_publish(cmd[native_arg_start:])
        else route.npm_registry_url
    )
    _replace_npm_registry_arg(cmd, native_arg_start, registry_url)
    env["NPM_CONFIG_REGISTRY"] = registry_url
    _inject_npm_auth(env, [registry_url], token)
    if isolate:
        empty_npmrc = temp_dir / "npmrc"
        empty_npmrc.write_text("", encoding="utf-8")
        env["NPM_CONFIG_USERCONFIG"] = str(empty_npmrc)
        env["NPM_CONFIG_GLOBALCONFIG"] = str(empty_npmrc)


def _npm_is_publish(argv: list[str]) -> bool:
    return any(arg == "publish" for arg in argv if not arg.startswith("-"))


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
        auth_key = _npm_auth_token_key(url)
        env[f"NPM_CONFIG_{auth_key}"] = token


def _npm_auth_token_key(registry_url: str) -> str:
    parsed = urlparse(registry_url)
    path = parsed.path or "/"
    if not path.endswith("/"):
        path += "/"
    return f"//{parsed.netloc}{path}:_authToken"


def _write_netrc(
    env: dict[str, str],
    urls: list[str],
    token: str,
    temp_dir: Path,
) -> None:
    hosts = sorted({urlparse(url).netloc for url in urls if urlparse(url).netloc})
    if not hosts:
        return
    netrc_path = temp_dir / "netrc"
    lines = [f"machine {host} login __token__ password {token}" for host in hosts]
    netrc_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    netrc_path.chmod(0o600)
    env["NETRC"] = str(netrc_path)


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
    server_ids = _maven_server_ids_for_urls(urls, argv)
    if route is not None:
        server_ids.add("rvs-private")
        _ensure_maven_profile(root, route)
    if not server_ids:
        server_ids.add("rvs-private")
    servers = _ensure_xml_child(root, "servers")
    for server_id in sorted(server_ids):
        _upsert_maven_server(servers, server_id, token)

    settings_path = temp_dir / "settings.xml"
    ET.ElementTree(root).write(settings_path, encoding="utf-8", xml_declaration=True)
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
        except (OSError, ET.ParseError):
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


def _ensure_maven_profile(root: ET.Element, route: RegistryRoute) -> None:
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
