"""Exact-target Docker, Helm, and ORAS launchers over one OCI endpoint."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import typer

from .. import config as cfg_mod
from .. import output
from ..account.commands import resolve_account
from ..client import ApiClient, ApiError
from ..pkg.targets import resolve_target
from ..runtime import tools
from ..subprocesses import child_environment


OciTool = Literal["docker", "helm", "oras"]
OciRegistryKind = Literal["container", "helm"]
_OCI_COMPONENT = re.compile(r"^[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*$")
_UNIQUE_ID = re.compile(r"^[23456789abcdefghijkmnpqrstuvwxyz]{8}$")


@dataclass(frozen=True)
class OciOptions:
    profile: str | None = None
    target: str | None = None
    account: str | None = None
    customer_id: str | None = None
    kind: OciRegistryKind | None = None


@dataclass(frozen=True)
class OciRoute:
    kind: OciRegistryKind
    registry_url: str
    registry_host: str
    native_root: str
    accepted_roots: frozenset[str]
    package_token: str


def _native_route_parts(native_path: str) -> tuple[str, str] | None:
    parts = native_path.strip("/").split("/")
    if len(parts) != 2:
        return None
    workspace, repository = parts
    stable = workspace.startswith("w_") or repository.startswith("r_")
    if stable:
        if not (
            workspace.startswith("w_")
            and repository.startswith("r_")
            and _UNIQUE_ID.fullmatch(workspace.removeprefix("w_"))
            and _UNIQUE_ID.fullmatch(repository.removeprefix("r_"))
        ):
            return None
    elif (
        not _OCI_COMPONENT.fullmatch(workspace)
        or not _OCI_COMPONENT.fullmatch(repository)
        or workspace.startswith(("w_", "r_"))
        or repository.startswith(("w_", "r_"))
    ):
        return None
    return workspace, repository


def _stable_oci_root(workspace_unique_ref: object, repository_unique_ref: object) -> str:
    if not isinstance(workspace_unique_ref, str) or not isinstance(repository_unique_ref, str):
        output.fatal("Invalid OCI capability response: stable identity is missing.")
    if not workspace_unique_ref.startswith("w_") or not repository_unique_ref.startswith("r_"):
        output.fatal("Invalid OCI capability response: stable identity is invalid.")
    workspace_id = workspace_unique_ref.removeprefix("w_")
    repository_id = repository_unique_ref.removeprefix("r_")
    if not _UNIQUE_ID.fullmatch(workspace_id) or not _UNIQUE_ID.fullmatch(repository_id):
        output.fatal("Invalid OCI capability response: stable identity is invalid.")
    return f"{workspace_unique_ref}/{repository_unique_ref}"


def _registry_url(profile: cfg_mod.ProfileConfig) -> tuple[str, str]:
    raw = profile.native_registries.oci_registry_base_url
    try:
        value = cfg_mod.validate_service_url(raw, label="OCI registry URL")
        parsed = urlsplit(value)
    except ValueError as exc:
        output.fatal(str(exc))
    if parsed.path not in {"", "/"}:
        output.fatal("OCI registry URL must not contain a path.")
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return value, host


def _selected_kind(tool: OciTool, selected: OciRegistryKind | None) -> OciRegistryKind:
    if tool == "docker":
        if selected not in {None, "container"}:
            output.fatal("rvs docker only supports the container registry kind.")
        return "container"
    if tool == "helm":
        if selected not in {None, "helm"}:
            output.fatal("rvs helm only supports the helm registry kind.")
        return "helm"
    if selected not in {"container", "helm"}:
        output.fatal("rvs oras requires --rvs-kind container or --rvs-kind helm.")
    return selected


def resolve_route(tool: OciTool, options: OciOptions) -> OciRoute:
    kind = _selected_kind(tool, options.kind)
    config = cfg_mod.load()
    profile_name = options.profile or cfg_mod.current_profile_name(config)
    customer_id = options.customer_id
    if customer_id is None and options.account is not None:
        customer_id = str(resolve_account(options.account, profile_name)["customer_id"])
    customer_id = customer_id or cfg_mod.current_customer_id(profile_name)
    selected = cfg_mod.selected_package_target(profile_name, customer_id)
    repo_ref = options.target
    if repo_ref is None and selected is not None:
        if selected.target_type != "private":
            output.fatal("OCI commands require a private repository target.")
        repo_ref = selected.stable_selector
    if repo_ref is None:
        repo_ref = config.registry_defaults(kind, profile_name).default_repo
    if not repo_ref:
        output.fatal(f"No {kind} repository selected. Pass --rvs-target or run `rvs pkg select`.")
    _, _, target = resolve_target(
        repo_ref,
        profile=profile_name,
        customer_id=customer_id,
        kind=kind,
    )
    if target.target_type != "private" or target.repository_id is None:
        output.fatal("OCI commands require a private repository target.")
    try:
        client = ApiClient.from_profile(profile_name)
        credential_body: dict[str, object] = {
            "repository_id": target.repository_id,
            "registry_kind": kind,
            "expected_target": {
                "workspace_id": target.workspace_id,
                "workspace_unique_ref": target.workspace_unique_ref,
                "workspace_name": target.workspace_name_cache,
                "repository_id": target.repository_id,
                "repository_unique_ref": target.repository_unique_ref,
                "repository_name": target.repository_name_cache,
            },
        }
        credential = client.post(
            "/v0/package-credentials",
            json=credential_body,
        ).json()
        token = credential["access_token"]
        native_path = credential["native_path"]
    except ApiError as exc:
        output.fatal(str(exc))
    except (KeyError, TypeError, ValueError) as exc:
        output.fatal(f"Invalid OCI capability response: {exc}")
    if not isinstance(native_path, str) or _native_route_parts(native_path) is None:
        output.fatal("Invalid OCI capability response: native_path is not canonical.")
    registry_url, registry_host = _registry_url(config.active_profile(profile_name))
    friendly_root = native_path.strip("/")
    stable_root = _stable_oci_root(
        credential.get("workspace_unique_ref"),
        credential.get("repository_unique_ref"),
    )
    return OciRoute(
        kind=kind,
        registry_url=registry_url,
        registry_host=registry_host,
        native_root=f"{registry_host}{native_path}",
        accepted_roots=frozenset((friendly_root, stable_root)),
        package_token=token,
    )


def _ravenstash_routes(argv: list[str], registry_host: str) -> set[str]:
    marker = f"{registry_host}/"
    routes: set[str] = set()
    for argument in argv:
        start = 0
        while (index := argument.find(marker, start)) >= 0:
            suffix = argument[index + len(marker) :]
            candidate = re.split(r"[\s,;\]\[(){}]", suffix, maxsplit=1)[0]
            parts = candidate.split("/")
            if len(parts) >= 2 and _native_route_parts("/".join(parts[:2])) is not None:
                routes.add("/".join(parts[:2]))
            start = index + len(marker)
    return routes


def _assert_exact_targets(argv: list[str], route: OciRoute) -> None:
    observed = _ravenstash_routes(argv, route.registry_host)
    if any(value not in route.accepted_roots for value in observed):
        output.fatal(
            "This invocation references another Ravenstash logical repository. "
            "One native invocation may use only the exact --rvs-target value."
        )


def _write_broker(temp_dir: Path, route: OciRoute) -> Path:
    path = temp_dir / "oci-credential.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "server": route.registry_host,
                "username": "__token__",
                "secret": route.package_token,
            },
            handle,
            separators=(",", ":"),
        )
        handle.flush()
        os.fsync(handle.fileno())
    return path


def _registry_config_source(tool: OciTool) -> Path:
    if tool == "helm":
        configured = os.environ.get("HELM_REGISTRY_CONFIG")
        if configured:
            return Path(configured).expanduser()
        config_home = os.environ.get("XDG_CONFIG_HOME")
        root = Path(config_home).expanduser() if config_home else Path.home() / ".config"
        return root / "helm" / "registry" / "config.json"
    docker_config = os.environ.get("DOCKER_CONFIG")
    root = Path(docker_config).expanduser() if docker_config else Path.home() / ".docker"
    return root / "config.json"


def _registry_entry_host(value: str) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urlsplit(candidate if "://" in candidate else f"https://{candidate}")
    if not parsed.hostname:
        return ""
    host = parsed.hostname.rstrip(".").lower()
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return host


def _native_registry_config(tool: OciTool) -> dict[str, object]:
    source = _registry_config_source(tool)
    try:
        if not source.is_file():
            return {}
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        output.fatal(f"Cannot read native {tool} registry config {source}: {exc}")
    if not isinstance(value, dict):
        output.fatal(f"Native {tool} registry config {source} must be an object.")
    return value


def _write_registry_config(temp_dir: Path, route: OciRoute, tool: OciTool) -> Path:
    config = _native_registry_config(tool)
    auths = config.get("auths")
    if isinstance(auths, dict):
        config["auths"] = {
            key: value
            for key, value in auths.items()
            if not isinstance(key, str) or _registry_entry_host(key) != route.registry_host
        }
    helpers = config.get("credHelpers")
    if not isinstance(helpers, dict):
        helpers = {}
    else:
        helpers = {
            key: value
            for key, value in helpers.items()
            if not isinstance(key, str) or _registry_entry_host(key) != route.registry_host
        }
    helpers[route.registry_host] = "rvs"
    config["credHelpers"] = helpers
    path = temp_dir / "config.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(config, handle, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    return path


def _executable(tool: OciTool) -> str:
    path = tools.require(tool, install_kind="system")
    try:
        if Path(path).resolve() == Path(os.environ.get("RVS_EXECUTABLE", "")).resolve():
            output.fatal(f"Refusing recursive {tool} executable resolution.")
    except OSError:
        pass
    return path


def run(tool: OciTool, argv: list[str], options: OciOptions) -> None:
    route = resolve_route(tool, options)
    _assert_exact_targets(argv, route)
    with tempfile.TemporaryDirectory(prefix="rvs-oci-") as temporary:
        temp_dir = Path(temporary)
        broker = _write_broker(temp_dir, route)
        registry_config = _write_registry_config(temp_dir, route, tool)
        env = child_environment(
            {
                "DOCKER_CONFIG": str(temp_dir),
                "HELM_REGISTRY_CONFIG": str(registry_config),
                "RVS_OCI_CREDENTIAL_FILE": str(broker),
            }
        )
        process = subprocess.Popen([_executable(tool), *argv], env=env)
        forwarded_signals = tuple(
            candidate
            for candidate in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
            if candidate is not None
        )
        previous_handlers = {signum: signal.getsignal(signum) for signum in forwarded_signals}

        def _forward(signum: int, _frame) -> None:
            if process.poll() is None:
                process.send_signal(signum)

        try:
            for signum in forwarded_signals:
                signal.signal(signum, _forward)
            returncode = process.wait()
        finally:
            for signum, previous in previous_handlers.items():
                signal.signal(signum, previous)
        if returncode:
            raise typer.Exit(128 - returncode if returncode < 0 else returncode)


def reference(
    *,
    kind: OciRegistryKind,
    options: OciOptions,
    oci_path: str | None,
    reference_value: str | None,
) -> str:
    route = resolve_route("oras", OciOptions(**{**options.__dict__, "kind": kind}))
    result = route.native_root
    if oci_path:
        components = oci_path.strip("/").split("/")
        if not components or any(not _OCI_COMPONENT.fullmatch(item) for item in components):
            output.fatal("OCI path contains an invalid repository component.")
        result = f"{result}/{'/'.join(components)}"
    if reference_value:
        if not oci_path:
            output.fatal("--reference requires --oci-path.")
        separator = "@" if reference_value.startswith("sha256:") else ":"
        result = f"{result}{separator}{reference_value}"
    return result


__all__ = ["OciOptions", "OciRegistryKind", "OciTool", "reference", "resolve_route", "run"]
