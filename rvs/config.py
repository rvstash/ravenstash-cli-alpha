"""Config file management for rvs.

Config lives at ~/.rvs/config.toml and supports multiple named profiles.
The effective local profile is resolved by:
  1. --profile CLI flag  (highest priority)
  2. RVS_PROFILE environment variable
  3. default_profile key in config file  (default: "default")

Config file shape
-----------------
::

    config_version = 3
    default_profile = "default"

    [profiles.default]
    api_url = "https://api.ravenstash.com"
    credential_store = "keyring"
    customer_id = "cus_..."
    customer_unique_id = "a8f3k2mz"
    credential_type = "expiring"
    expires_at = "2026-06-17T16:00:00+00:00"
    refresh_expires_at = "2026-06-17T20:00:00+00:00"

    [profiles.default.native_registries.pypi]
    read_base_url = "https://pypi.rvsta.sh"
    push_base_url = "https://push.pypi.rvsta.sh"
    mirror_base_url = "https://mirror.pypi.rvsta.sh"

    [profiles.default.native_registries.npm]
    read_base_url = "https://npm.rvsta.sh"
    push_base_url = "https://push.npm.rvsta.sh"
    mirror_base_url = "https://mirror.npm.rvsta.sh"

    [profiles.default.native_registries.maven]
    read_base_url = "https://maven.rvsta.sh"
    push_base_url = "https://push.maven.rvsta.sh"
    mirror_base_url = "https://mirror.maven.rvsta.sh"

    [profiles.default.native_registries.oci]
    registry_base_url = "https://oci.rvsta.sh"

    [profiles.default.registries.pypi]
    default_repo = "in_abcdefgh/r_m7nk3p4q"

    [profiles.default.registries.npm]
    default_repo = "in_abcdefgh/r_n4b6v8cx"

    [profiles.default.registries.maven]
    default_repo = "in_abcdefgh/r_p2q4r6st"
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit, urlunsplit

import tomli_w

from .paths import rvs_home


RegistryKind = Literal["pypi", "npm", "maven", "container", "helm"]
ArtifactTargetType = Literal["repository", "official_cache", "custom_cache"]
NamespaceRealm = Literal["internal", "global"]

CONFIG_DIR = rvs_home()
CONFIG_FILE = CONFIG_DIR / "config.toml"
PROFILE_ENV_FILE = CONFIG_DIR / "profiles.env"
LOCAL_ENV_FILE_NAME = ".rvs.env"
SESSIONS_DIR_NAME = "sessions"

DEFAULT_API_URL = "https://api.ravenstash.com"
DEFAULT_REPOSITORY_DOMAIN = "rvsta.sh"
CURRENT_CONFIG_VERSION = 3
_UNIQUE_ID_FRAGMENT = r"[23456789abcdefghijkmnpqrstuvwxyz]{8}"
_INTERNAL_NAMESPACE_REF_RE = re.compile(rf"^in_{_UNIQUE_ID_FRAGMENT}$")
_GLOBAL_NAMESPACE_REF_RE = re.compile(rf"^gn_{_UNIQUE_ID_FRAGMENT}$")
_REPOSITORY_REF_RE = re.compile(rf"^r_{_UNIQUE_ID_FRAGMENT}$")


@dataclass(frozen=True)
class PackageRegistryEndpoints:
    read_base_url: str
    push_base_url: str
    mirror_base_url: str


@dataclass(frozen=True)
class NativeRegistryEndpoints:
    pypi: PackageRegistryEndpoints
    npm: PackageRegistryEndpoints
    maven: PackageRegistryEndpoints
    oci_registry_base_url: str

    def package(self, kind: Literal["pypi", "npm", "maven"]) -> PackageRegistryEndpoints:
        return cast("PackageRegistryEndpoints", getattr(self, kind))


def repository_domain_summary(endpoints: NativeRegistryEndpoints) -> str:
    """Summarize a conventional native-registry endpoint family by DNS suffix."""
    service_urls = (
        (("pypi",), endpoints.pypi.read_base_url),
        (("push.pypi",), endpoints.pypi.push_base_url),
        (("mirror.pypi",), endpoints.pypi.mirror_base_url),
        (("npm",), endpoints.npm.read_base_url),
        (("push.npm",), endpoints.npm.push_base_url),
        (("mirror.npm",), endpoints.npm.mirror_base_url),
        (("maven",), endpoints.maven.read_base_url),
        (("push.maven",), endpoints.maven.push_base_url),
        (("mirror.maven",), endpoints.maven.mirror_base_url),
        (("oci",), endpoints.oci_registry_base_url),
    )
    hosts = [urlsplit(url).hostname or "" for _services, url in service_urls]
    domains = {
        host.removeprefix(f"{service}.")
        for (services, _url), host in zip(service_urls, hosts, strict=True)
        for service in services
        if host.startswith(f"{service}.")
    }
    if len(domains) == 1 and all(
        any(host == f"{service}.{next(iter(domains))}" for service in services)
        for (services, _url), host in zip(service_urls, hosts, strict=True)
    ):
        return next(iter(domains))

    unique_hosts = set(hosts)
    if len(unique_hosts) == 1 and hosts[0] and _is_loopback_host(hosts[0]):
        return hosts[0]
    return "custom endpoints"


def _is_loopback_host(hostname: str) -> bool:
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_service_url(value: str, *, label: str) -> str:
    """Validate and normalize a credential-bearing Ravenstash service URL."""
    candidate = value.strip().rstrip("/")
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{label} must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{label} must not contain user information")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{label} must not contain a query string or fragment")
    if parsed.scheme == "http" and not _is_loopback_host(parsed.hostname):
        raise ValueError(f"{label} must use HTTPS unless it targets loopback")

    hostname = parsed.hostname.rstrip(".").lower()
    if ":" in hostname:
        host = f"[{hostname}]"
    else:
        host = hostname
    if parsed.port is not None:
        default_port = 443 if parsed.scheme == "https" else 80
        if parsed.port != default_port:
            host = f"{host}:{parsed.port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), host, path, "", ""))


@dataclass
class ProfileConfig:
    api_url: str = DEFAULT_API_URL
    native_registries: NativeRegistryEndpoints = field(
        default_factory=lambda: _default_native_registries("default")
    )
    customer_id: str | None = None
    customer_unique_id: str | None = None
    credential_store: str | None = None
    credential_type: str | None = None
    expires_at: str | None = None
    refresh_expires_at: str | None = None
    active_customer_id: str | None = None
    accounts: dict[str, AccountContext] = field(default_factory=dict)
    registries: dict[RegistryKind, RegistryDefaults] = field(default_factory=dict)


@dataclass
class ArtifactTarget:
    target_type: ArtifactTargetType
    customer_id: str
    stable_selector: str
    display_selector: str
    registry_kind: RegistryKind | None = None
    namespace_realm: NamespaceRealm | None = None
    namespace_unique_ref: str | None = None
    namespace_name_cache: str | None = None
    repository_unique_ref: str | None = None
    repository_name_cache: str | None = None
    remote_id: str | None = None
    remote_unique_ref: str | None = None
    remote_name_cache: str | None = None
    source_id: str | None = None
    is_available: bool = True


@dataclass
class AccountContext:
    customer_id: str
    customer_unique_ref: str
    account_type: Literal["personal", "organization"]
    account_label: str
    organization_role: str | None = None
    authority_revision: int | None = None
    selected_target: ArtifactTarget | None = None
    customer_handle: str | None = None


@dataclass
class SessionContext:
    profile: str | None = None
    customer_id: str | None = None


@dataclass
class RegistryDefaults:
    default_repo: str | None = None
    customer_id: str | None = None
    customer_unique_ref: str | None = None
    namespace_realm: NamespaceRealm | None = None
    namespace_unique_ref: str | None = None
    namespace_name_cache: str | None = None
    repository_unique_ref: str | None = None
    repository_name_cache: str | None = None
    organization_role: str | None = None
    authority_revision: int | None = None
    is_available: bool = True


@dataclass
class RvsConfig:
    default_profile: str = "default"
    credential_store: str = "auto"
    profiles: dict[str, ProfileConfig] = field(default_factory=dict)

    def active_profile(self, profile_name: str | None = None) -> ProfileConfig:
        name = profile_name or os.environ.get("RVS_PROFILE") or self.default_profile
        return self.profiles.get(name, _default_profile_config(name))

    def registry_defaults(
        self,
        kind: RegistryKind,
        profile_name: str | None = None,
    ) -> RegistryDefaults:
        name = profile_name or os.environ.get("RVS_PROFILE") or self.default_profile
        profile = self.profiles.get(name)
        if profile and kind in profile.registries:
            return profile.registries[kind]
        return RegistryDefaults()


def current_profile_name(cfg: RvsConfig | None = None) -> str:
    """Return the effective named local CLI profile."""
    resolved_cfg = cfg or load()
    session = load_session()
    return os.environ.get("RVS_PROFILE") or session.profile or resolved_cfg.default_profile


def profile_selection_source() -> str:
    """Describe what selected the effective local CLI profile."""
    if os.environ.get("RVS_PROFILE"):
        return "environment (RVS_PROFILE)"
    if load_session().profile:
        return "shell session"
    return "persisted default"


def current_customer_id(
    profile_name: str | None = None,
    cfg: RvsConfig | None = None,
) -> str | None:
    """Return the active customer for a profile, including this shell's override."""
    resolved_cfg = cfg or load()
    effective_profile = profile_name or current_profile_name(resolved_cfg)
    explicit = os.environ.get("RVS_CUSTOMER_ID")
    if explicit:
        return explicit
    session = load_session()
    if session.customer_id and (session.profile is None or session.profile == effective_profile):
        return session.customer_id
    profile = resolved_cfg.profiles.get(effective_profile)
    if profile is None:
        return None
    return profile.active_customer_id or profile.customer_id


def account_selection_source(
    profile_name: str | None = None,
    cfg: RvsConfig | None = None,
) -> str:
    """Describe what selected the effective acting account."""
    resolved_cfg = cfg or load()
    effective_profile = profile_name or current_profile_name(resolved_cfg)
    if os.environ.get("RVS_CUSTOMER_ID"):
        return "environment (RVS_CUSTOMER_ID)"
    session = load_session()
    if session.customer_id and (session.profile is None or session.profile == effective_profile):
        return "shell session"
    profile = resolved_cfg.profiles.get(effective_profile)
    if profile is None:
        return "not selected"
    if profile.active_customer_id:
        return "persisted profile"
    if profile.customer_id:
        return "personal account default"
    return "not selected"


def profile_selection_write_scope() -> str:
    """Return where a local-profile selection is persisted."""
    return "shell session" if _session_file() is not None else "persisted default"


def account_selection_write_scope() -> str:
    """Return where an acting-account selection is persisted."""
    return "shell session" if _session_file() is not None else "persisted profile"


def _session_file() -> Path | None:
    session_id = os.environ.get("RVS_SESSION_ID", "").strip()
    if not session_id:
        return None
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    return CONFIG_DIR / SESSIONS_DIR_NAME / f"{digest}.toml"


def load_session() -> SessionContext:
    path = _session_file()
    if path is None or not path.exists():
        return SessionContext()
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except OSError, tomllib.TOMLDecodeError:
        return SessionContext()
    return SessionContext(
        profile=raw.get("profile") if isinstance(raw.get("profile"), str) else None,
        customer_id=(raw.get("customer_id") if isinstance(raw.get("customer_id"), str) else None),
    )


def save_session(session: SessionContext) -> bool:
    """Persist non-secret shell-local context; return False without shell integration."""
    path = _session_file()
    if path is None:
        return False
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    raw = {
        key: value
        for key, value in {
            "profile": session.profile,
            "customer_id": session.customer_id,
        }.items()
        if value is not None
    }
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            os.fchmod(temporary.fileno(), 0o600)
            tomli_w.dump(raw, temporary)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        path.chmod(0o600)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return True


# ── Environment helpers ───────────────────────────────────────────────────────


def _profile_env_key(profile_name: str, suffix: str = "API_URL") -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", profile_name).strip("_").upper()
    return f"RVS_PROFILE_{normalized}_{suffix}"


def _parse_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if key:
            values[key] = _parse_env_value(value)
    return values


def _nearest_local_env_file() -> Path | None:
    current = Path.cwd()
    for directory in (current, *current.parents):
        candidate = directory / LOCAL_ENV_FILE_NAME
        if candidate.exists():
            return candidate
    return None


def _env_file_values() -> dict[str, str]:
    values = _read_env_file(PROFILE_ENV_FILE)
    local_env_file = _nearest_local_env_file()
    if local_env_file is not None:
        values.update(_read_env_file(local_env_file))
    explicit_env_file = os.environ.get("RVS_ENV_FILE")
    if explicit_env_file:
        values.update(_read_env_file(Path(explicit_env_file).expanduser()))
    return values


def _env_value(name: str) -> str | None:
    return os.environ.get(name) or _env_file_values().get(name)


def profile_api_url(profile_name: str) -> str:
    """Return the default API URL for *profile_name* from env/config defaults."""
    return _profile_api_url_override(profile_name) or DEFAULT_API_URL


def _profile_api_url_override(profile_name: str) -> str | None:
    keys = [_profile_env_key(profile_name)]
    if profile_name == "default":
        keys.append("RVS_API_URL")
    for key in keys:
        value = _env_value(key)
        if value:
            return validate_service_url(value, label=f"{profile_name} API URL")
    return None


def validate_repository_domain(value: str, *, label: str) -> str:
    """Validate and normalize a package-repository DNS suffix."""
    candidate = value.strip().lower().rstrip(".")
    if candidate.startswith("*."):
        candidate = candidate[2:]
    if not candidate or len(candidate) > 253:
        raise ValueError(f"{label} must be a valid DNS domain")
    invalid_label = any(
        len(part) > 63 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", part)
        for part in candidate.split(".")
    )
    if invalid_label:
        raise ValueError(f"{label} must be a valid DNS domain without a scheme, port, or path")
    return candidate


def _profile_repository_domain_override(profile_name: str) -> str | None:
    keys = [_profile_env_key(profile_name, "REPOSITORY_DOMAIN")]
    if profile_name == "default":
        keys.append("RVS_REPOSITORY_DOMAIN")
    for key in keys:
        value = _env_value(key)
        if value:
            return validate_repository_domain(value, label=f"{profile_name} repository domain")
    return None


def profile_repository_domain(profile_name: str) -> str:
    """Return the repository DNS suffix selected for a profile."""
    return _profile_repository_domain_override(profile_name) or DEFAULT_REPOSITORY_DOMAIN


def _repository_service_url(
    domain: str,
    service: str,
    *,
    source_url: str | None = None,
) -> str:
    source = urlsplit(source_url) if source_url is not None else None
    scheme = source.scheme if source is not None else "https"
    is_localhost = domain == "localhost" or domain.endswith(".localhost")
    if is_localhost:
        scheme = "http"
    host = "localhost" if is_localhost else f"{service}.{domain}"
    if source is not None and source.port is not None:
        host = f"{host}:{source.port}"
    path = source.path if source is not None else ""
    return validate_service_url(
        urlunsplit((scheme, host, path, "", "")),
        label=f"{service} repository URL",
    )


def _package_registry_endpoints(
    profile_name: str,
    kind: Literal["pypi", "npm", "maven"],
    source: PackageRegistryEndpoints | None = None,
) -> PackageRegistryEndpoints:
    domain_override = _profile_repository_domain_override(profile_name)
    if source is not None and domain_override is None:
        return source
    domain = domain_override or DEFAULT_REPOSITORY_DOMAIN
    return PackageRegistryEndpoints(
        read_base_url=_repository_service_url(
            domain,
            kind,
            source_url=source.read_base_url if source is not None else None,
        ),
        push_base_url=_repository_service_url(
            domain,
            f"push.{kind}",
            source_url=source.push_base_url if source is not None else None,
        ),
        mirror_base_url=_repository_service_url(
            domain,
            f"mirror.{kind}",
            source_url=source.mirror_base_url if source is not None else None,
        ),
    )


def _default_native_registries(profile_name: str) -> NativeRegistryEndpoints:
    return NativeRegistryEndpoints(
        pypi=_package_registry_endpoints(profile_name, "pypi"),
        npm=_package_registry_endpoints(profile_name, "npm"),
        maven=_package_registry_endpoints(profile_name, "maven"),
        oci_registry_base_url=_repository_service_url(
            profile_repository_domain(profile_name),
            "oci",
        ),
    )


def _native_registries_from_mapping(
    value: object,
    *,
    profile_name: str,
) -> NativeRegistryEndpoints:
    if value is None:
        return _default_native_registries(profile_name)
    if not isinstance(value, dict):
        raise ValueError(f"{profile_name} native registry endpoints must be a table")

    def package(kind: Literal["pypi", "npm", "maven"]) -> PackageRegistryEndpoints:
        raw = value.get(kind)
        if not isinstance(raw, dict):
            raise ValueError(f"{profile_name} {kind} registry endpoints are missing")
        try:
            discovered = PackageRegistryEndpoints(
                read_base_url=validate_service_url(
                    str(raw["read_base_url"]), label=f"{profile_name} {kind} read URL"
                ),
                push_base_url=validate_service_url(
                    str(raw["push_base_url"]), label=f"{profile_name} {kind} push URL"
                ),
                mirror_base_url=validate_service_url(
                    str(raw["mirror_base_url"]),
                    label=f"{profile_name} {kind} mirror URL",
                ),
            )
            return _package_registry_endpoints(profile_name, kind, discovered)
        except KeyError as exc:
            raise ValueError(f"{profile_name} {kind} registry endpoints are incomplete") from exc

    raw_oci = value.get("container") or value.get("oci")
    if not isinstance(raw_oci, dict) or "registry_base_url" not in raw_oci:
        raise ValueError(f"{profile_name} container registry endpoint is missing")
    raw_helm = value.get("helm")
    if isinstance(raw_helm, dict) and raw_helm.get("registry_base_url") != raw_oci.get(
        "registry_base_url"
    ):
        raise ValueError(
            f"{profile_name} container and Helm registry endpoints must share one OCI host"
        )
    discovered_oci_url = validate_service_url(
        str(raw_oci["registry_base_url"]), label=f"{profile_name} OCI registry URL"
    )
    domain_override = _profile_repository_domain_override(profile_name)
    return NativeRegistryEndpoints(
        pypi=package("pypi"),
        npm=package("npm"),
        maven=package("maven"),
        oci_registry_base_url=(
            _repository_service_url(domain_override, "oci", source_url=discovered_oci_url)
            if domain_override is not None
            else discovered_oci_url
        ),
    )


def _default_profile_config(profile_name: str) -> ProfileConfig:
    return ProfileConfig(
        api_url=profile_api_url(profile_name),
        native_registries=_default_native_registries(profile_name),
    )


def _artifact_target_from_mapping(value: object) -> ArtifactTarget | None:
    if not isinstance(value, dict):
        return None
    target_type = value.get("target_type")
    customer_id = value.get("customer_id")
    stable_selector = value.get("stable_selector")
    display_selector = value.get("display_selector")
    if target_type not in {"repository", "official_cache", "custom_cache"}:
        return None
    if not all(
        isinstance(item, str) and item for item in (customer_id, stable_selector, display_selector)
    ):
        return None
    registry_kind = value.get("registry_kind")
    if registry_kind not in {None, "pypi", "npm", "maven", "container", "helm"}:
        return None
    return ArtifactTarget(
        target_type=cast("ArtifactTargetType", target_type),
        customer_id=cast("str", customer_id),
        stable_selector=cast("str", stable_selector),
        display_selector=cast("str", display_selector),
        registry_kind=cast("RegistryKind | None", registry_kind),
        namespace_realm=value.get("namespace_realm"),
        namespace_unique_ref=value.get("namespace_unique_ref"),
        namespace_name_cache=value.get("namespace_name_cache"),
        repository_unique_ref=value.get("repository_unique_ref"),
        repository_name_cache=value.get("repository_name_cache"),
        remote_id=value.get("remote_id"),
        remote_unique_ref=value.get("remote_unique_ref"),
        remote_name_cache=value.get("remote_name_cache"),
        source_id=value.get("source_id"),
        is_available=value.get("is_available", True),
    )


def _account_contexts_from_mapping(value: object) -> dict[str, AccountContext]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, AccountContext] = {}
    for customer_id, raw in value.items():
        if not isinstance(customer_id, str) or not isinstance(raw, dict):
            continue
        account_type = raw.get("account_type")
        unique_ref = raw.get("customer_unique_ref")
        label = raw.get("account_label")
        if account_type not in {"personal", "organization"}:
            continue
        if not isinstance(unique_ref, str) or not isinstance(label, str):
            continue
        result[customer_id] = AccountContext(
            customer_id=customer_id,
            customer_unique_ref=unique_ref,
            account_type=account_type,
            account_label=label,
            organization_role=raw.get("organization_role"),
            authority_revision=raw.get("authority_revision"),
            selected_target=_artifact_target_from_mapping(raw.get("selected_target")),
            customer_handle=raw.get("customer_handle"),
        )
    return result


def _artifact_target_mapping(target: ArtifactTarget) -> dict:
    return {
        key: value
        for key, value in vars(target).items()
        if value is not None and not (key == "is_available" and value is True)
    }


def _account_context_mapping(account: AccountContext) -> dict:
    return {
        key: value
        for key, value in {
            "customer_unique_ref": account.customer_unique_ref,
            "account_type": account.account_type,
            "account_label": account.account_label,
            "customer_handle": account.customer_handle,
            "organization_role": account.organization_role,
            "authority_revision": account.authority_revision,
            "selected_target": (
                _artifact_target_mapping(account.selected_target)
                if account.selected_target is not None
                else None
            ),
        }.items()
        if value is not None
    }


# ── Serialisation helpers ─────────────────────────────────────────────────────


def _load_raw() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with CONFIG_FILE.open("rb") as f:
        return tomllib.load(f)


def _canonical_mirror_url(value: str, kind: Literal["pypi", "npm", "maven"]) -> str:
    """Move a conventional pre-rename cache host to its mirror hostname."""
    parsed = urlsplit(value)
    hostname = parsed.hostname
    legacy_prefix = f"cache.{kind}."
    if (
        hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or not hostname.lower().startswith(legacy_prefix)
    ):
        return value
    canonical_hostname = f"mirror.{kind}.{hostname[len(legacy_prefix) :]}"
    netloc = canonical_hostname
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _migrate_config_v0_to_v1(raw: dict) -> None:
    """Rename discovered cache endpoints without disturbing unrelated profile data."""
    profiles = raw.get("profiles")
    if isinstance(profiles, dict):
        for profile in profiles.values():
            if not isinstance(profile, dict):
                continue
            native_registries = profile.get("native_registries")
            if not isinstance(native_registries, dict):
                continue
            for kind in ("pypi", "npm", "maven"):
                endpoints = native_registries.get(kind)
                if not isinstance(endpoints, dict):
                    continue
                legacy_url = endpoints.pop("cache_base_url", None)
                if "mirror_base_url" not in endpoints and legacy_url is not None:
                    endpoints["mirror_base_url"] = _canonical_mirror_url(str(legacy_url), kind)
    raw["config_version"] = 1


def _migrate_config_v1_to_v2(raw: dict) -> None:
    """Rename persisted workspace fields and retire service-private identifiers."""

    def normalized_namespace_ref(value: object) -> object:
        if isinstance(value, str) and value.startswith("w_"):
            return f"in_{value[2:]}"
        return value

    def rename_field(value: dict, old: str, new: str, *, path: str) -> None:
        if old not in value:
            return
        old_value = value[old]
        new_value = value.get(new)
        normalized_old = (
            normalized_namespace_ref(old_value) if old == "workspace_unique_ref" else old_value
        )
        normalized_new = (
            normalized_namespace_ref(new_value) if new == "namespace_unique_ref" else new_value
        )
        if new in value and normalized_new != normalized_old:
            raise ValueError(f"conflicting legacy and current values at {path}.{new}")
        value[new] = normalized_old
        value.pop(old)

    def migrate_target(value: object, *, path: str) -> None:
        if not isinstance(value, dict):
            return
        if value.get("target_type") == "private":
            value["target_type"] = "repository"
        is_repository = value.get("target_type") == "repository" or (
            "default_repo" in value
            and isinstance(value.get("default_repo"), str)
            and not str(value["default_repo"]).startswith(("mirror:", "custom-mirror:"))
        )
        for old, new in (
            ("workspace_unique_ref", "namespace_unique_ref"),
            ("workspace_name_cache", "namespace_name_cache"),
        ):
            rename_field(value, old, new, path=path)
        value.pop("workspace_id", None)
        value.pop("namespace_id", None)
        value.pop("repository_id", None)
        if "namespace_unique_ref" in value:
            value["namespace_unique_ref"] = normalized_namespace_ref(value["namespace_unique_ref"])
        for selector_key in ("stable_selector", "default_repo"):
            selector = value.get(selector_key)
            if isinstance(selector, str) and selector.startswith("w_"):
                value[selector_key] = f"in_{selector[2:]}"
            elif (
                isinstance(selector, str)
                and is_repository
                and ":" not in selector
                and selector.count("/") == 1
                and not selector.startswith(("in_", "gn_"))
            ):
                value[selector_key] = f"internal:{selector}"
        display_selector = value.get("display_selector")
        if (
            isinstance(display_selector, str)
            and value.get("target_type") == "repository"
            and ":" not in display_selector
            and display_selector.count("/") == 1
            and not display_selector.startswith(("in_", "gn_"))
        ):
            value["display_selector"] = f"internal:{display_selector}"
        if is_repository:
            value["namespace_realm"] = "internal"

    profiles = raw.get("profiles")
    if isinstance(profiles, dict):
        for profile_name, profile in profiles.items():
            if not isinstance(profile, dict):
                continue
            accounts = profile.get("accounts")
            if isinstance(accounts, dict):
                for customer_id, account in accounts.items():
                    if isinstance(account, dict):
                        migrate_target(
                            account.get("selected_target"),
                            path=f"profiles.{profile_name}.accounts.{customer_id}.selected_target",
                        )
            registries = profile.get("registries")
            if isinstance(registries, dict):
                for registry_kind, defaults in registries.items():
                    migrate_target(
                        defaults,
                        path=f"profiles.{profile_name}.registries.{registry_kind}",
                    )
    raw["config_version"] = 2


def _migrate_raw_config(raw: dict) -> bool:
    """Apply every config migration needed by this CLI release in order."""
    raw_version = raw.get("config_version", 0)
    if isinstance(raw_version, bool) or not isinstance(raw_version, int) or raw_version < 0:
        raise ValueError("config_version must be a non-negative integer")
    version: int = raw_version
    if version > CURRENT_CONFIG_VERSION:
        raise ValueError(
            f"config version {version} requires a newer rvs release "
            f"(this release supports version {CURRENT_CONFIG_VERSION})"
        )

    changed = False
    while version < CURRENT_CONFIG_VERSION:
        if version == 0:
            _migrate_config_v0_to_v1(raw)
        elif version == 1:
            _migrate_config_v1_to_v2(raw)
        elif version == 2:
            _migrate_config_v2_to_v3(raw)
        else:
            raise RuntimeError(f"rvs has no config migration from version {version}")
        next_version = raw.get("config_version")
        if (
            isinstance(next_version, bool)
            or not isinstance(next_version, int)
            or next_version != version + 1
        ):
            raise RuntimeError(
                f"config migration from version {version} did not produce version {version + 1}"
            )
        version = next_version
        changed = True
    return changed


def _migrate_config_v2_to_v3(raw: dict) -> None:
    """Remove obsolete selector notation while preserving account and resource IDs."""
    profiles = raw.get("profiles", {})
    if isinstance(profiles, dict):
        for profile in profiles.values():
            if not isinstance(profile, dict):
                continue
            targets = []
            accounts = profile.get("accounts", {})
            if isinstance(accounts, dict):
                targets.extend(
                    account.get("selected_target")
                    for account in accounts.values()
                    if isinstance(account, dict)
                )
            registries = profile.get("registries", {})
            if isinstance(registries, dict):
                targets.extend(registries.values())
            for target in targets:
                if not isinstance(target, dict):
                    continue
                for key in ("stable_selector", "display_selector", "default_repo"):
                    selector = target.get(key)
                    if isinstance(selector, str) and selector.startswith(("internal:", "global:")):
                        realm = target.get("namespace_realm", "internal")
                        if key != "display_selector" and selector.split(":", 1)[0] != realm:
                            raise ValueError(
                                "repository selector conflicts with its namespace realm"
                            )
                        target[key] = selector.split(":", 1)[1]
    raw["config_version"] = 3


def _validate_repository_target_identity(
    value: dict, *, path: str, allow_legacy_short_selector: bool = False
) -> None:
    realm = value.get("namespace_realm", "internal" if "default_repo" in value else None)
    if realm not in {"internal", "global"}:
        raise ValueError(f"invalid namespace realm at {path}.namespace_realm")
    namespace_ref = value.get("namespace_unique_ref")
    repository_ref = value.get("repository_unique_ref")
    expected_namespace = (
        _INTERNAL_NAMESPACE_REF_RE if realm == "internal" else _GLOBAL_NAMESPACE_REF_RE
    )
    if namespace_ref is not None and (
        not isinstance(namespace_ref, str) or expected_namespace.fullmatch(namespace_ref) is None
    ):
        raise ValueError(f"invalid namespace reference at {path}.namespace_unique_ref")
    if repository_ref is not None and (
        not isinstance(repository_ref, str) or _REPOSITORY_REF_RE.fullmatch(repository_ref) is None
    ):
        raise ValueError(f"invalid repository reference at {path}.repository_unique_ref")

    selector = value.get("stable_selector", value.get("default_repo"))
    if not isinstance(selector, str) or not selector:
        raise ValueError(f"missing repository selector at {path}")
    if selector.startswith(("in_", "gn_", "w_", "r_")):
        parts = selector.split("/")
        if (
            len(parts) != 2
            or expected_namespace.fullmatch(parts[0]) is None
            or _REPOSITORY_REF_RE.fullmatch(parts[1]) is None
        ):
            raise ValueError(f"invalid stable repository selector at {path}")
        if namespace_ref is not None and namespace_ref != parts[0]:
            raise ValueError(f"conflicting namespace identity at {path}")
        if repository_ref is not None and repository_ref != parts[1]:
            raise ValueError(f"conflicting repository identity at {path}")
    elif (
        selector.startswith("@")
        or ":" in selector
        or (selector.count("/") != 1 and not (allow_legacy_short_selector and "/" not in selector))
    ):
        raise ValueError(f"invalid repository selector at {path}")


def _validate_raw_config(raw: dict) -> None:
    """Fail closed on malformed current config before replacing the source file."""

    profiles = raw.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ValueError("profiles must be a table")
    for profile_name, profile in profiles.items():
        profile_path = f"profiles.{profile_name}"
        if not isinstance(profile_name, str) or not isinstance(profile, dict):
            raise ValueError(f"invalid profile table at {profile_path}")
        accounts = profile.get("accounts", {})
        if not isinstance(accounts, dict):
            raise ValueError(f"accounts must be a table at {profile_path}.accounts")
        for customer_id, account in accounts.items():
            account_path = f"{profile_path}.accounts.{customer_id}"
            if not isinstance(customer_id, str) or not isinstance(account, dict):
                raise ValueError(f"invalid account table at {account_path}")
            selected = account.get("selected_target")
            if selected is None:
                continue
            target_path = f"{account_path}.selected_target"
            if not isinstance(selected, dict) or _artifact_target_from_mapping(selected) is None:
                raise ValueError(f"invalid selected target at {target_path}")
            if selected.get("target_type") == "repository":
                _validate_repository_target_identity(selected, path=target_path)

        registries = profile.get("registries", {})
        if not isinstance(registries, dict):
            raise ValueError(f"registries must be a table at {profile_path}.registries")
        for registry_kind, defaults in registries.items():
            target_path = f"{profile_path}.registries.{registry_kind}"
            if registry_kind not in {"pypi", "npm", "maven", "container", "helm"}:
                raise ValueError(f"invalid registry kind at {target_path}")
            if not isinstance(defaults, dict):
                raise ValueError(f"invalid registry defaults at {target_path}")
            selector = defaults.get("default_repo")
            if selector is not None:
                if not isinstance(selector, str) or not selector:
                    raise ValueError(f"invalid default repository at {target_path}")
                if not selector.startswith(("mirror:", "custom-mirror:")):
                    _validate_repository_target_identity(
                        defaults,
                        path=target_path,
                        allow_legacy_short_selector=True,
                    )


def _write_raw(raw: dict) -> None:
    """Atomically persist an already validated config mapping."""
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    CONFIG_DIR.chmod(0o700)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=CONFIG_DIR,
            prefix=".config.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            os.fchmod(temporary.fileno(), 0o600)
            tomli_w.dump(raw, temporary)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, CONFIG_FILE)
        CONFIG_FILE.chmod(0o600)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _backup_pre_migration_config(version: int) -> None:
    """Create an owner-only source backup before replacing a versioned config."""
    backup_path = CONFIG_FILE.with_name(f"config.v{version}.toml.bak")
    try:
        descriptor = os.open(
            backup_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        return
    try:
        with os.fdopen(descriptor, "wb") as backup:
            backup.write(CONFIG_FILE.read_bytes())
            backup.flush()
            os.fsync(backup.fileno())
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise


def stored_profile_api_url(profile_name: str) -> str | None:
    """Return a profile's persisted DevAPI URL without environment overrides."""
    # Device login may use this accessor before any other config call. Run the
    # ordinary validated loader first so every pending migration is durably
    # committed (and backed up) before the caller can make a network request.
    load()
    raw = _load_raw()
    profiles = raw.get("profiles")
    if not isinstance(profiles, dict):
        return None
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        return None
    value = profile.get("api_url")
    if not isinstance(value, str):
        return None
    return validate_service_url(value, label=f"{profile_name} stored API URL")


def load() -> RvsConfig:
    config_exists = CONFIG_FILE.exists()
    raw = _load_raw()
    original_version = raw.get("config_version", 0)
    migrated = _migrate_raw_config(raw)
    _validate_raw_config(raw)
    cfg = RvsConfig(
        default_profile=raw.get("default_profile", "default"),
        credential_store=raw.get("credential_store", "auto"),
    )

    for name, vals in raw.get("profiles", {}).items():
        api_url_override = _profile_api_url_override(name)
        cfg.profiles[name] = ProfileConfig(
            api_url=validate_service_url(
                api_url_override or vals.get("api_url", DEFAULT_API_URL),
                label=f"{name} API URL",
            ),
            native_registries=_native_registries_from_mapping(
                vals.get("native_registries"), profile_name=name
            ),
            customer_id=vals.get("customer_id"),
            customer_unique_id=vals.get("customer_unique_id"),
            credential_store=vals.get("credential_store"),
            credential_type=vals.get("credential_type"),
            expires_at=vals.get("expires_at"),
            refresh_expires_at=vals.get("refresh_expires_at"),
            active_customer_id=vals.get("active_customer_id"),
            accounts=_account_contexts_from_mapping(vals.get("accounts")),
            registries={
                kind: RegistryDefaults(
                    default_repo=defaults.get("default_repo"),
                    customer_id=defaults.get("customer_id"),
                    customer_unique_ref=defaults.get("customer_unique_ref"),
                    namespace_realm=defaults.get("namespace_realm"),
                    namespace_unique_ref=defaults.get("namespace_unique_ref"),
                    namespace_name_cache=defaults.get("namespace_name_cache"),
                    repository_unique_ref=defaults.get("repository_unique_ref"),
                    repository_name_cache=defaults.get("repository_name_cache"),
                    organization_role=defaults.get("organization_role"),
                    authority_revision=defaults.get("authority_revision"),
                    is_available=defaults.get("is_available", True),
                )
                for kind, defaults in vals.get("registries", {}).items()
            },
        )

    if migrated and config_exists:
        if isinstance(original_version, int):
            _backup_pre_migration_config(original_version)
        _write_raw(raw)
    return cfg


def save(cfg: RvsConfig) -> None:
    raw: dict = {
        "config_version": CURRENT_CONFIG_VERSION,
        "default_profile": cfg.default_profile,
        "credential_store": cfg.credential_store,
    }

    if cfg.profiles:
        raw["profiles"] = {
            name: {
                k: v
                for k, v in {
                    "api_url": p.api_url,
                    "native_registries": {
                        "pypi": vars(p.native_registries.pypi),
                        "npm": vars(p.native_registries.npm),
                        "maven": vars(p.native_registries.maven),
                        "oci": {"registry_base_url": p.native_registries.oci_registry_base_url},
                    },
                    "customer_id": p.customer_id,
                    "customer_unique_id": p.customer_unique_id,
                    "credential_store": p.credential_store,
                    "credential_type": p.credential_type,
                    "expires_at": p.expires_at,
                    "refresh_expires_at": p.refresh_expires_at,
                    "active_customer_id": p.active_customer_id,
                    "accounts": {
                        customer_id: _account_context_mapping(account)
                        for customer_id, account in p.accounts.items()
                    }
                    or None,
                    "registries": {
                        kind: {
                            key: value
                            for key, value in {
                                "default_repo": defaults.default_repo,
                                "customer_id": defaults.customer_id,
                                "customer_unique_ref": defaults.customer_unique_ref,
                                "namespace_realm": defaults.namespace_realm,
                                "namespace_unique_ref": defaults.namespace_unique_ref,
                                "namespace_name_cache": defaults.namespace_name_cache,
                                "repository_unique_ref": defaults.repository_unique_ref,
                                "repository_name_cache": defaults.repository_name_cache,
                                "organization_role": defaults.organization_role,
                                "authority_revision": defaults.authority_revision,
                                "is_available": (None if defaults.is_available else False),
                            }.items()
                            if value is not None
                        }
                        for kind, defaults in p.registries.items()
                        if defaults.default_repo is not None
                    }
                    or None,
                }.items()
                if v is not None
            }
            for name, p in cfg.profiles.items()
        }

    _write_raw(raw)


# ── Convenience setters ───────────────────────────────────────────────────────


def set_profile_value(profile: str, api_url: str | None = None) -> None:
    cfg = load()
    existing = cfg.profiles.get(profile, _default_profile_config(profile))
    cfg.profiles[profile] = ProfileConfig(
        api_url=validate_service_url(api_url, label=f"{profile} API URL")
        if api_url is not None
        else existing.api_url,
        native_registries=existing.native_registries,
        customer_id=existing.customer_id,
        customer_unique_id=existing.customer_unique_id,
        credential_store=existing.credential_store,
        credential_type=existing.credential_type,
        expires_at=existing.expires_at,
        refresh_expires_at=existing.refresh_expires_at,
        active_customer_id=existing.active_customer_id,
        accounts=existing.accounts,
        registries=existing.registries,
    )
    save(cfg)


def clear_profile_credential_metadata(profile: str) -> None:
    cfg = load()
    existing = cfg.profiles.get(profile)
    if existing is None:
        return
    cfg.profiles[profile] = ProfileConfig(
        api_url=existing.api_url,
        native_registries=existing.native_registries,
        customer_id=None,
        customer_unique_id=None,
        credential_store=existing.credential_store,
        credential_type=None,
        expires_at=None,
        refresh_expires_at=None,
        active_customer_id=existing.active_customer_id,
        accounts=existing.accounts,
        registries=existing.registries,
    )
    save(cfg)


def set_profile_metadata(
    profile: str,
    *,
    api_url: str | None = None,
    native_registries: object | None = None,
    customer_id: str | None = None,
    customer_unique_id: str | None = None,
    credential_store: str | None = None,
    credential_type: str | None = None,
    expires_at: str | None = None,
    refresh_expires_at: str | None = None,
) -> None:
    cfg = load()
    existing = cfg.profiles.get(profile, _default_profile_config(profile))
    cfg.profiles[profile] = ProfileConfig(
        api_url=validate_service_url(api_url, label=f"{profile} API URL")
        if api_url is not None
        else existing.api_url,
        native_registries=(
            _native_registries_from_mapping(native_registries, profile_name=profile)
            if native_registries is not None
            else existing.native_registries
        ),
        customer_id=customer_id if customer_id is not None else existing.customer_id,
        customer_unique_id=customer_unique_id
        if customer_unique_id is not None
        else existing.customer_unique_id,
        credential_store=credential_store
        if credential_store is not None
        else existing.credential_store,
        credential_type=credential_type
        if credential_type is not None
        else existing.credential_type,
        expires_at=expires_at if expires_at is not None else existing.expires_at,
        refresh_expires_at=refresh_expires_at
        if refresh_expires_at is not None
        else existing.refresh_expires_at,
        active_customer_id=existing.active_customer_id,
        accounts=existing.accounts,
        registries=existing.registries,
    )
    save(cfg)


def set_credential_store(store: str) -> None:
    """Set the preferred credential store for future device logins."""
    if store not in {"auto", "keyring", "pass", "vault", "plaintext"}:
        raise ValueError("Credential store must be auto, keyring, pass, vault, or plaintext")
    cfg = load()
    cfg.credential_store = store
    save(cfg)


def set_default_profile(profile: str) -> None:
    session = load_session()
    if _session_file() is not None:
        session.profile = profile
        session.customer_id = None
        save_session(session)
        return
    cfg = load()
    cfg.default_profile = profile
    save(cfg)


def set_active_account(
    *,
    profile: str,
    customer: dict,
) -> AccountContext:
    """Select and cache one authorized customer for a local profile."""
    return cache_account(profile=profile, customer=customer, activate=True)


def cache_account(
    *,
    profile: str,
    customer: dict,
    activate: bool = False,
) -> AccountContext:
    """Cache safe account metadata, optionally making the account active."""
    cfg = load()
    profile_config = cfg.profiles.get(profile, _default_profile_config(profile))
    customer_id = str(customer["customer_id"])
    existing = profile_config.accounts.get(customer_id)
    account = AccountContext(
        customer_id=customer_id,
        customer_unique_ref=str(customer["customer_unique_ref"]),
        account_type=cast("Literal['personal', 'organization']", customer["account_type"]),
        account_label=str(customer["account_label"]),
        customer_handle=customer.get("customer_handle"),
        organization_role=customer.get("organization_role"),
        authority_revision=customer.get("authority_revision"),
        selected_target=existing.selected_target if existing is not None else None,
    )
    profile_config.accounts[customer_id] = account
    session_scoped = _session_file() is not None
    if activate and not session_scoped:
        profile_config.active_customer_id = customer_id
    cfg.profiles[profile] = profile_config
    save(cfg)
    session = load_session()
    if activate and session_scoped:
        session.profile = profile
        session.customer_id = customer_id
        save_session(session)
    return account


def cached_account(
    profile: str | None = None,
    customer_id: str | None = None,
) -> AccountContext | None:
    cfg = load()
    profile_name = profile or current_profile_name(cfg)
    effective_customer_id = customer_id or current_customer_id(profile_name, cfg)
    if not effective_customer_id:
        return None
    profile_config = cfg.profiles.get(profile_name)
    return profile_config.accounts.get(effective_customer_id) if profile_config else None


def selected_artifact_target(
    profile: str | None = None,
    customer_id: str | None = None,
) -> ArtifactTarget | None:
    account = cached_account(profile, customer_id)
    return account.selected_target if account is not None else None


def set_selected_artifact_target(
    target: ArtifactTarget | None,
    *,
    profile: str | None = None,
    customer_id: str | None = None,
) -> None:
    cfg = load()
    profile_name = profile or current_profile_name(cfg)
    effective_customer_id = customer_id or current_customer_id(profile_name, cfg)
    if not effective_customer_id:
        raise ValueError("No acting account is selected")
    profile_config = cfg.profiles.get(profile_name, _default_profile_config(profile_name))
    account = profile_config.accounts.get(effective_customer_id)
    if account is None:
        raise ValueError("The selected acting account has not been resolved")
    account.selected_target = target
    profile_config.accounts[effective_customer_id] = account
    cfg.profiles[profile_name] = profile_config
    save(cfg)


def delete_profile(profile: str) -> bool:
    cfg = load()
    if profile not in cfg.profiles:
        return False

    del cfg.profiles[profile]
    if cfg.default_profile == profile:
        cfg.default_profile = next(iter(cfg.profiles), "default")
    save(cfg)
    session = load_session()
    if session.profile == profile:
        session.profile = cfg.default_profile
        session.customer_id = None
        save_session(session)
    return True


def delete_all_profiles() -> None:
    cfg = load()
    cfg.profiles = {}
    cfg.default_profile = "default"
    save(cfg)
    if _session_file() is not None:
        save_session(SessionContext(profile="default"))


def set_registry_default_repo(
    kind: RegistryKind,
    repo: str,
    profile: str | None = None,
) -> None:
    cfg = load()
    profile_name = profile or current_profile_name(cfg)
    profile_config = cfg.profiles.get(profile_name, _default_profile_config(profile_name))
    profile_config.registries[kind] = RegistryDefaults(default_repo=repo)
    cfg.profiles[profile_name] = profile_config
    save(cfg)


def set_registry_default_target(
    kind: RegistryKind,
    *,
    customer: dict,
    repository: dict,
    profile: str | None = None,
) -> None:
    """Persist immutable authority plus refreshable display-name caches."""
    cfg = load()
    profile_name = profile or current_profile_name(cfg)
    profile_config = cfg.profiles.get(profile_name, _default_profile_config(profile_name))
    stable_selector = f"{repository['namespace_unique_ref']}/{repository['repository_unique_ref']}"
    profile_config.registries[kind] = RegistryDefaults(
        default_repo=stable_selector,
        customer_id=customer["customer_id"],
        customer_unique_ref=customer["customer_unique_ref"],
        namespace_realm=repository["namespace_realm"],
        namespace_unique_ref=repository["namespace_unique_ref"],
        namespace_name_cache=repository["namespace_name"],
        repository_unique_ref=repository["repository_unique_ref"],
        repository_name_cache=repository["repository_name"],
        organization_role=customer.get("organization_role"),
        authority_revision=customer.get("authority_revision"),
        is_available=True,
    )
    cfg.profiles[profile_name] = profile_config
    save(cfg)


def registry_target_expectation(
    kind: RegistryKind,
    selector: str,
    profile: str | None = None,
) -> dict[str, str] | None:
    """Return a complete saved identity/name guard for the selected stable target."""
    cfg = load()
    profile_name = profile or current_profile_name(cfg)
    target = cfg.registry_defaults(kind, profile_name)
    stable_selector = (
        f"{target.namespace_unique_ref}/{target.repository_unique_ref}"
        if target.namespace_unique_ref and target.repository_unique_ref
        else None
    )
    if selector != stable_selector:
        return None
    expected = {
        "namespace_unique_ref": target.namespace_unique_ref,
        "namespace_name": target.namespace_name_cache,
        "namespace_realm": target.namespace_realm,
        "repository_unique_ref": target.repository_unique_ref,
        "repository_name": target.repository_name_cache,
    }
    if not all(isinstance(value, str) and value for value in expected.values()):
        return None
    return {key: value for key, value in expected.items() if isinstance(value, str)}


def repository_target_snapshot(repository: dict) -> dict[str, str]:
    """Build the identity/name guard returned by repository resolution."""
    keys = (
        "namespace_unique_ref",
        "namespace_name",
        "namespace_realm",
        "repository_unique_ref",
        "repository_name",
    )
    values = {key: repository.get(key) for key in keys}
    if not all(isinstance(value, str) and value for value in values.values()):
        raise ValueError("Repository resolution omitted target identity or name metadata")
    return {
        "namespace_unique_ref": cast("str", values["namespace_unique_ref"]),
        "namespace_name": cast("str", values["namespace_name"]),
        "namespace_realm": cast("str", values["namespace_realm"]),
        "repository_unique_ref": cast("str", values["repository_unique_ref"]),
        "repository_name": cast("str", values["repository_name"]),
    }


def refresh_matching_registry_targets(
    *,
    customer: dict,
    repository: dict,
    profile: str | None = None,
) -> None:
    """Refresh saved names after an explicit CLI rename of the same identity."""
    cfg = load()
    profile_name = profile or current_profile_name(cfg)
    profile_config = cfg.profiles.get(profile_name, _default_profile_config(profile_name))
    stable_selector = f"{repository['namespace_unique_ref']}/{repository['repository_unique_ref']}"
    for kind, target in tuple(profile_config.registries.items()):
        if target.default_repo != stable_selector:
            continue
        profile_config.registries[kind] = RegistryDefaults(
            default_repo=stable_selector,
            customer_id=customer["customer_id"],
            customer_unique_ref=customer["customer_unique_ref"],
            namespace_realm=repository["namespace_realm"],
            namespace_unique_ref=repository["namespace_unique_ref"],
            namespace_name_cache=repository["namespace_name"],
            repository_unique_ref=repository["repository_unique_ref"],
            repository_name_cache=repository["repository_name"],
            organization_role=customer.get("organization_role"),
            authority_revision=customer.get("authority_revision"),
            is_available=True,
        )
    cfg.profiles[profile_name] = profile_config
    save(cfg)


def mark_registry_default_unavailable(kind: RegistryKind, profile: str | None = None) -> None:
    """Keep an immutable saved target but record that current authority denied it."""
    cfg = load()
    profile_name = profile or current_profile_name(cfg)
    profile_config = cfg.profiles.get(profile_name)
    if profile_config is None or kind not in profile_config.registries:
        return
    profile_config.registries[kind].is_available = False
    save(cfg)
