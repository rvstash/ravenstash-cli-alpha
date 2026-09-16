"""Config file management for rvs.

Config lives at ~/.rvs/config.toml and supports multiple named profiles.
The effective local profile is resolved by:
  1. --profile CLI flag  (highest priority)
  2. RVS_PROFILE environment variable
  3. default_profile key in config file  (default: "default")

Config file shape
-----------------
::

    config_version = 6
    default_profile = "default"

    [profiles.default]
    api_url = "https://api.ravenstash.com"
    credential_store = "keyring"
    account_ref = "ac_a8f3k2mz"
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


RegistryKind = Literal["pypi", "npm", "maven", "oci"]
ArtifactTargetType = Literal["repository", "official_cache", "custom_cache"]
NamespaceRealm = Literal["internal", "global"]

CONFIG_DIR = rvs_home()
CONFIG_FILE = CONFIG_DIR / "config.toml"
PROFILE_ENV_FILE = CONFIG_DIR / "profiles.env"
LOCAL_ENV_FILE_NAME = ".rvs.env"
SESSIONS_DIR_NAME = "sessions"

DEFAULT_API_URL = "https://api.ravenstash.com"
DEFAULT_REPOSITORY_DOMAIN = "rvsta.sh"
CURRENT_CONFIG_VERSION = 6


class ConfigError(ValueError):
    """A user-actionable failure while reading the local configuration."""


_UNIQUE_ID_FRAGMENT = r"[23456789abcdefghijkmnpqrstuvwxyz]{8}"
_ACCOUNT_REF_RE = re.compile(rf"^ac_{_UNIQUE_ID_FRAGMENT}$")
_INTERNAL_NAMESPACE_REF_RE = re.compile(rf"^in_{_UNIQUE_ID_FRAGMENT}$")
_GLOBAL_NAMESPACE_REF_RE = re.compile(rf"^gn_{_UNIQUE_ID_FRAGMENT}$")
_REPOSITORY_REF_RE = re.compile(rf"^ar_{_UNIQUE_ID_FRAGMENT}$")


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
    credential_store: str | None = None
    credential_type: str | None = None
    expires_at: str | None = None
    refresh_expires_at: str | None = None
    active_customer_id: str | None = None
    accounts: dict[str, AccountContext] = field(default_factory=dict)


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
class RvsConfig:
    default_profile: str = "default"
    credential_store: str = "auto"
    profiles: dict[str, ProfileConfig] = field(default_factory=dict)

    def active_profile(self, profile_name: str | None = None) -> ProfileConfig:
        name = profile_name or os.environ.get("RVS_PROFILE") or self.default_profile
        return self.profiles.get(name, _default_profile_config(name))


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
    """Return the active account for a profile, including this shell's override."""
    resolved_cfg = cfg or load()
    effective_profile = profile_name or current_profile_name(resolved_cfg)
    explicit = os.environ.get("RVS_ACCOUNT_REF")
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
    if os.environ.get("RVS_ACCOUNT_REF"):
        return "environment (RVS_ACCOUNT_REF)"
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
        customer_id=(raw.get("account_ref") if isinstance(raw.get("account_ref"), str) else None),
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
            "account_ref": session.customer_id,
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
            if hasattr(os, "fchmod"):
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

    raw_oci = value.get("oci")
    if not isinstance(raw_oci, dict) or "registry_base_url" not in raw_oci:
        raise ValueError(f"{profile_name} OCI registry endpoint is missing")
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
    customer_id = value.get("account_ref")
    stable_selector = value.get("stable_selector")
    display_selector = value.get("display_selector")
    if target_type not in {"repository", "official_cache", "custom_cache"}:
        return None
    if not all(
        isinstance(item, str) and item for item in (customer_id, stable_selector, display_selector)
    ):
        return None
    registry_kind = value.get("format")
    if registry_kind not in {None, "pypi", "npm", "maven", "oci"}:
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
    for account_ref, raw in value.items():
        if not isinstance(account_ref, str) or not isinstance(raw, dict):
            continue
        account_type = raw.get("account_type")
        label = raw.get("account_label")
        if account_type not in {"personal", "organization"}:
            continue
        if not account_ref or not isinstance(label, str):
            continue
        result[account_ref] = AccountContext(
            customer_id=account_ref,
            customer_unique_ref=account_ref,
            account_type=account_type,
            account_label=label,
            organization_role=raw.get("organization_role"),
            authority_revision=raw.get("authority_revision"),
            selected_target=_artifact_target_from_mapping(raw.get("selected_target")),
            customer_handle=raw.get("account_handle"),
        )
    return result


def _artifact_target_mapping(target: ArtifactTarget) -> dict:
    return {
        key: value
        for key, value in {
            **vars(target),
            "account_ref": target.customer_id,
            "format": target.registry_kind,
        }.items()
        if key not in {"customer_id", "registry_kind"}
        if value is not None and not (key == "is_available" and value is True)
    }


def _account_context_mapping(account: AccountContext) -> dict:
    return {
        key: value
        for key, value in {
            "account_type": account.account_type,
            "account_label": account.account_label,
            "account_handle": account.customer_handle,
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


def _normalize_raw_config(raw: dict) -> None:
    if not raw:
        raw["config_version"] = CURRENT_CONFIG_VERSION
        return
    version = raw.get("config_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("config_version must be an integer")
    if version != CURRENT_CONFIG_VERSION:
        raise ValueError(
            f"config version {version} is not supported "
            f"(this release requires version {CURRENT_CONFIG_VERSION})"
        )


def _validate_repository_target_identity(value: dict, *, path: str) -> None:
    realm = value.get("namespace_realm")
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

    selector = value.get("stable_selector")
    if not isinstance(selector, str) or not selector:
        raise ValueError(f"missing repository selector at {path}")
    if selector.split("/", 1)[-1].startswith("ar_"):
        parts = selector.split("/")
        if len(parts) != 2 or parts[0] != "in" or _REPOSITORY_REF_RE.fullmatch(parts[1]) is None:
            raise ValueError(f"invalid stable repository selector at {path}")
        if repository_ref is not None and repository_ref != parts[1]:
            raise ValueError(f"conflicting repository identity at {path}")
    elif selector.startswith("@") or ":" in selector or selector.count("/") != 1:
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
        for account_ref, account in accounts.items():
            account_path = f"{profile_path}.accounts.{account_ref}"
            if not isinstance(account_ref, str) or not account_ref or not isinstance(account, dict):
                raise ValueError(f"invalid account table at {account_path}")
            selected = account.get("selected_target")
            if selected is None:
                continue
            target_path = f"{account_path}.selected_target"
            if not isinstance(selected, dict) or _artifact_target_from_mapping(selected) is None:
                raise ValueError(f"invalid selected target at {target_path}")
            if selected.get("target_type") == "repository":
                _validate_repository_target_identity(selected, path=target_path)


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
            if hasattr(os, "fchmod"):
                os.fchmod(temporary.fileno(), 0o600)
            tomli_w.dump(raw, temporary)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, CONFIG_FILE)
        CONFIG_FILE.chmod(0o600)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def stored_profile_api_url(profile_name: str) -> str | None:
    """Return a profile's persisted DevAPI URL without environment overrides."""
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


def _load_validated() -> RvsConfig:
    raw = _load_raw()
    _normalize_raw_config(raw)
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
            customer_id=vals.get("account_ref"),
            credential_store=vals.get("credential_store"),
            credential_type=vals.get("credential_type"),
            expires_at=vals.get("expires_at"),
            refresh_expires_at=vals.get("refresh_expires_at"),
            active_customer_id=vals.get("active_account_ref"),
            accounts=_account_contexts_from_mapping(vals.get("accounts")),
        )

    return cfg


def load() -> RvsConfig:
    """Load configuration and identify failures that users can repair locally."""
    try:
        return _load_validated()
    except ConfigError:
        raise
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        raise ConfigError(f"could not read {CONFIG_FILE}: {exc}") from exc


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
                    "account_ref": p.customer_id,
                    "credential_store": p.credential_store,
                    "credential_type": p.credential_type,
                    "expires_at": p.expires_at,
                    "refresh_expires_at": p.refresh_expires_at,
                    "active_account_ref": p.active_customer_id,
                    "accounts": {
                        account_ref: _account_context_mapping(account)
                        for account_ref, account in p.accounts.items()
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
        credential_store=existing.credential_store,
        credential_type=existing.credential_type,
        expires_at=existing.expires_at,
        refresh_expires_at=existing.refresh_expires_at,
        active_customer_id=existing.active_customer_id,
        accounts=existing.accounts,
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
        credential_store=existing.credential_store,
        credential_type=None,
        expires_at=None,
        refresh_expires_at=None,
        active_customer_id=existing.active_customer_id,
        accounts=existing.accounts,
    )
    save(cfg)


def set_profile_metadata(
    profile: str,
    *,
    api_url: str | None = None,
    native_registries: object | None = None,
    customer_id: str | None = None,
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
    """Select and cache one authorized account for a local profile."""
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
    customer_id = str(customer["account_ref"])
    existing = profile_config.accounts.get(customer_id)
    account = AccountContext(
        customer_id=customer_id,
        customer_unique_ref=customer_id,
        account_type=cast("Literal['personal', 'organization']", customer["account_type"]),
        account_label=str(customer["account_label"]),
        customer_handle=customer.get("account_handle"),
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
        raise ValueError("No account is selected")
    profile_config = cfg.profiles.get(profile_name, _default_profile_config(profile_name))
    account = profile_config.accounts.get(effective_customer_id)
    if account is None:
        raise ValueError("The selected account could not be found")
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


def profile_names_for_reset() -> list[str]:
    """Read profile names without requiring the config format to be supported."""
    try:
        raw = _load_raw()
    except OSError, tomllib.TOMLDecodeError:
        return []
    profiles = raw.get("profiles")
    if not isinstance(profiles, dict):
        return []
    return [name for name in profiles if isinstance(name, str)]


def delete_all_profiles() -> None:
    """Replace any local config version with an empty current-format baseline."""
    save(RvsConfig())
    if _session_file() is not None:
        save_session(SessionContext(profile="default"))
