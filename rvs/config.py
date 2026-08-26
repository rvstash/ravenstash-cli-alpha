"""Config file management for rvs.

Config lives at ~/.rvs/config.toml and supports multiple named profiles.
The active profile is resolved by:
  1. --profile CLI flag  (highest priority)
  2. RVS_PROFILE environment variable
  3. default_profile key in config file  (default: "default")

Config file shape
-----------------
::

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
    cache_base_url = "https://cache.pypi.rvsta.sh"

    [profiles.default.native_registries.npm]
    read_base_url = "https://npm.rvsta.sh"
    push_base_url = "https://push.npm.rvsta.sh"
    cache_base_url = "https://cache.npm.rvsta.sh"

    [profiles.default.native_registries.maven]
    read_base_url = "https://maven.rvsta.sh"
    push_base_url = "https://push.maven.rvsta.sh"
    cache_base_url = "https://cache.maven.rvsta.sh"

    [profiles.default.native_registries.oci]
    registry_base_url = "https://oci.rvsta.sh"

    [profiles.default.registries.pypi]
    default_repo = "_abcdefgh/_m7nk3p4q"

    [profiles.default.registries.npm]
    default_repo = "_abcdefgh/_n4b6v8cx"

    [profiles.default.registries.maven]
    default_repo = "_abcdefgh/_p2q4r6st"
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
PackageTargetType = Literal["private", "official_cache", "custom_cache"]

CONFIG_DIR = rvs_home()
CONFIG_FILE = CONFIG_DIR / "config.toml"
PROFILE_ENV_FILE = CONFIG_DIR / "profiles.env"
LOCAL_ENV_FILE_NAME = ".rvs.env"
SESSIONS_DIR_NAME = "sessions"

DEFAULT_API_URL = "https://api.ravenstash.com"


@dataclass(frozen=True)
class PackageRegistryEndpoints:
    read_base_url: str
    push_base_url: str
    cache_base_url: str


@dataclass(frozen=True)
class NativeRegistryEndpoints:
    pypi: PackageRegistryEndpoints
    npm: PackageRegistryEndpoints
    maven: PackageRegistryEndpoints
    oci_registry_base_url: str

    def package(self, kind: Literal["pypi", "npm", "maven"]) -> PackageRegistryEndpoints:
        return cast("PackageRegistryEndpoints", getattr(self, kind))


def _is_loopback_host(hostname: str) -> bool:
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost":
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
class PackageTarget:
    target_type: PackageTargetType
    customer_id: str
    stable_selector: str
    display_selector: str
    registry_kind: RegistryKind | None = None
    workspace_id: str | None = None
    workspace_unique_ref: str | None = None
    workspace_name_cache: str | None = None
    repository_id: str | None = None
    repository_unique_ref: str | None = None
    repository_name_cache: str | None = None
    remote_id: str | None = None
    remote_unique_ref: str | None = None
    remote_name_cache: str | None = None
    source_id: str | None = None
    direct_access_enabled: bool | None = None
    is_available: bool = True


@dataclass
class AccountContext:
    customer_id: str
    customer_unique_ref: str
    account_type: Literal["personal", "organization"]
    account_label: str
    organization_role: str | None = None
    authority_revision: int | None = None
    selected_target: PackageTarget | None = None


@dataclass
class SessionContext:
    profile: str | None = None
    customer_id: str | None = None


@dataclass
class RegistryDefaults:
    default_repo: str | None = None
    customer_id: str | None = None
    customer_unique_ref: str | None = None
    workspace_id: str | None = None
    workspace_unique_ref: str | None = None
    workspace_name_cache: str | None = None
    repository_id: str | None = None
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
    """Return the effective active profile name."""
    resolved_cfg = cfg or load()
    session = load_session()
    return os.environ.get("RVS_PROFILE") or session.profile or resolved_cfg.default_profile


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
    keys = [_profile_env_key(profile_name)]
    if profile_name == "default":
        keys.append("RVS_API_URL")
    for key in keys:
        value = _env_value(key)
        if value:
            return validate_service_url(value, label=f"{profile_name} API URL")
    return DEFAULT_API_URL


def _profile_service_url(
    profile_name: str,
    *,
    suffix: str,
    default_env_key: str,
    default_url: str,
) -> str:
    keys = [_profile_env_key(profile_name, suffix)]
    if profile_name == "default":
        keys.append(default_env_key)
    for key in keys:
        value = _env_value(key)
        if value:
            return validate_service_url(value, label=f"{profile_name} {suffix.lower()} URL")
    return validate_service_url(default_url, label=f"{profile_name} {suffix.lower()} URL")


def _package_registry_endpoints(
    profile_name: str,
    kind: Literal["pypi", "npm", "maven"],
) -> PackageRegistryEndpoints:
    upper = kind.upper()
    return PackageRegistryEndpoints(
        read_base_url=_profile_service_url(
            profile_name,
            suffix=f"{upper}_READ_URL",
            default_env_key=f"RVS_{upper}_READ_URL",
            default_url=f"https://{kind}.rvsta.sh",
        ),
        push_base_url=_profile_service_url(
            profile_name,
            suffix=f"{upper}_PUSH_URL",
            default_env_key=f"RVS_{upper}_PUSH_URL",
            default_url=f"https://push.{kind}.rvsta.sh",
        ),
        cache_base_url=_profile_service_url(
            profile_name,
            suffix=f"{upper}_CACHE_URL",
            default_env_key=f"RVS_{upper}_CACHE_URL",
            default_url=f"https://cache.{kind}.rvsta.sh",
        ),
    )


def _default_native_registries(profile_name: str) -> NativeRegistryEndpoints:
    return NativeRegistryEndpoints(
        pypi=_package_registry_endpoints(profile_name, "pypi"),
        npm=_package_registry_endpoints(profile_name, "npm"),
        maven=_package_registry_endpoints(profile_name, "maven"),
        oci_registry_base_url=_profile_service_url(
            profile_name,
            suffix="OCI_REGISTRY_URL",
            default_env_key="RVS_OCI_REGISTRY_URL",
            default_url="https://oci.rvsta.sh",
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
            return PackageRegistryEndpoints(
                read_base_url=validate_service_url(
                    str(raw["read_base_url"]), label=f"{profile_name} {kind} read URL"
                ),
                push_base_url=validate_service_url(
                    str(raw["push_base_url"]), label=f"{profile_name} {kind} push URL"
                ),
                cache_base_url=validate_service_url(
                    str(raw["cache_base_url"]), label=f"{profile_name} {kind} cache URL"
                ),
            )
        except KeyError as exc:
            raise ValueError(f"{profile_name} {kind} registry endpoints are incomplete") from exc

    raw_oci = value.get("oci")
    if not isinstance(raw_oci, dict) or "registry_base_url" not in raw_oci:
        raise ValueError(f"{profile_name} OCI registry endpoint is missing")
    return NativeRegistryEndpoints(
        pypi=package("pypi"),
        npm=package("npm"),
        maven=package("maven"),
        oci_registry_base_url=validate_service_url(
            str(raw_oci["registry_base_url"]), label=f"{profile_name} OCI registry URL"
        ),
    )


def _default_profile_config(profile_name: str) -> ProfileConfig:
    return ProfileConfig(
        api_url=profile_api_url(profile_name),
        native_registries=_default_native_registries(profile_name),
    )


def _package_target_from_mapping(value: object) -> PackageTarget | None:
    if not isinstance(value, dict):
        return None
    target_type = value.get("target_type")
    customer_id = value.get("customer_id")
    stable_selector = value.get("stable_selector")
    display_selector = value.get("display_selector")
    if target_type not in {"private", "official_cache", "custom_cache"}:
        return None
    if not all(
        isinstance(item, str) and item for item in (customer_id, stable_selector, display_selector)
    ):
        return None
    registry_kind = value.get("registry_kind")
    if registry_kind not in {None, "pypi", "npm", "maven", "container", "helm"}:
        return None
    return PackageTarget(
        target_type=cast("PackageTargetType", target_type),
        customer_id=cast("str", customer_id),
        stable_selector=cast("str", stable_selector),
        display_selector=cast("str", display_selector),
        registry_kind=cast("RegistryKind | None", registry_kind),
        workspace_id=value.get("workspace_id"),
        workspace_unique_ref=value.get("workspace_unique_ref"),
        workspace_name_cache=value.get("workspace_name_cache"),
        repository_id=value.get("repository_id"),
        repository_unique_ref=value.get("repository_unique_ref"),
        repository_name_cache=value.get("repository_name_cache"),
        remote_id=value.get("remote_id"),
        remote_unique_ref=value.get("remote_unique_ref"),
        remote_name_cache=value.get("remote_name_cache"),
        source_id=value.get("source_id"),
        direct_access_enabled=value.get("direct_access_enabled"),
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
            selected_target=_package_target_from_mapping(raw.get("selected_target")),
        )
    return result


def _package_target_mapping(target: PackageTarget) -> dict:
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
            "organization_role": account.organization_role,
            "authority_revision": account.authority_revision,
            "selected_target": (
                _package_target_mapping(account.selected_target)
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


def load() -> RvsConfig:
    raw = _load_raw()
    cfg = RvsConfig(
        default_profile=raw.get("default_profile", "default"),
        credential_store=raw.get("credential_store", "auto"),
    )

    for name, vals in raw.get("profiles", {}).items():
        cfg.profiles[name] = ProfileConfig(
            api_url=validate_service_url(
                vals.get("api_url", profile_api_url(name)),
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
                    workspace_id=defaults.get("workspace_id"),
                    workspace_unique_ref=defaults.get("workspace_unique_ref"),
                    workspace_name_cache=defaults.get("workspace_name_cache"),
                    repository_id=defaults.get("repository_id"),
                    repository_unique_ref=defaults.get("repository_unique_ref"),
                    repository_name_cache=defaults.get("repository_name_cache"),
                    organization_role=defaults.get("organization_role"),
                    authority_revision=defaults.get("authority_revision"),
                    is_available=defaults.get("is_available", True),
                )
                for kind, defaults in vals.get("registries", {}).items()
            },
        )

    return cfg


def save(cfg: RvsConfig) -> None:
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    CONFIG_DIR.chmod(0o700)
    raw: dict = {
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
                                "workspace_id": defaults.workspace_id,
                                "workspace_unique_ref": defaults.workspace_unique_ref,
                                "workspace_name_cache": defaults.workspace_name_cache,
                                "repository_id": defaults.repository_id,
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
    if store not in {"auto", "keyring", "pass"}:
        raise ValueError("Credential store must be auto, keyring, or pass")
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
    """Select and cache one authorized customer for a login profile."""
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


def selected_package_target(
    profile: str | None = None,
    customer_id: str | None = None,
) -> PackageTarget | None:
    account = cached_account(profile, customer_id)
    return account.selected_target if account is not None else None


def set_selected_package_target(
    target: PackageTarget | None,
    *,
    profile: str | None = None,
    customer_id: str | None = None,
) -> None:
    cfg = load()
    profile_name = profile or current_profile_name(cfg)
    effective_customer_id = customer_id or current_customer_id(profile_name, cfg)
    if not effective_customer_id:
        raise ValueError("No Ravenstash account is selected")
    profile_config = cfg.profiles.get(profile_name, _default_profile_config(profile_name))
    account = profile_config.accounts.get(effective_customer_id)
    if account is None:
        raise ValueError("The selected Ravenstash account has not been resolved")
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
    stable_selector = f"{repository['workspace_unique_ref']}/{repository['repository_unique_ref']}"
    profile_config.registries[kind] = RegistryDefaults(
        default_repo=stable_selector,
        customer_id=customer["customer_id"],
        customer_unique_ref=customer["customer_unique_ref"],
        workspace_id=repository["workspace_id"],
        workspace_unique_ref=repository["workspace_unique_ref"],
        workspace_name_cache=repository["workspace_name"],
        repository_id=repository["id"],
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
        f"{target.workspace_unique_ref}/{target.repository_unique_ref}"
        if target.workspace_unique_ref and target.repository_unique_ref
        else None
    )
    if selector != stable_selector:
        return None
    expected = {
        "workspace_id": target.workspace_id,
        "workspace_unique_ref": target.workspace_unique_ref,
        "workspace_name": target.workspace_name_cache,
        "repository_id": target.repository_id,
        "repository_unique_ref": target.repository_unique_ref,
        "repository_name": target.repository_name_cache,
    }
    if not all(isinstance(value, str) and value for value in expected.values()):
        return None
    return {key: value for key, value in expected.items() if isinstance(value, str)}


def repository_target_snapshot(repository: dict) -> dict[str, str]:
    """Build the identity/name guard returned by repository resolution."""
    keys = (
        "workspace_id",
        "workspace_unique_ref",
        "workspace_name",
        "id",
        "repository_unique_ref",
        "repository_name",
    )
    values = {key: repository.get(key) for key in keys}
    if not all(isinstance(value, str) and value for value in values.values()):
        raise ValueError("Repository resolution omitted target identity or name metadata")
    return {
        "workspace_id": cast("str", values["workspace_id"]),
        "workspace_unique_ref": cast("str", values["workspace_unique_ref"]),
        "workspace_name": cast("str", values["workspace_name"]),
        "repository_id": cast("str", values["id"]),
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
    stable_selector = f"{repository['workspace_unique_ref']}/{repository['repository_unique_ref']}"
    for kind, target in tuple(profile_config.registries.items()):
        if target.default_repo != stable_selector:
            continue
        profile_config.registries[kind] = RegistryDefaults(
            default_repo=stable_selector,
            customer_id=customer["customer_id"],
            customer_unique_ref=customer["customer_unique_ref"],
            workspace_id=repository["workspace_id"],
            workspace_unique_ref=repository["workspace_unique_ref"],
            workspace_name_cache=repository["workspace_name"],
            repository_id=repository["id"],
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
