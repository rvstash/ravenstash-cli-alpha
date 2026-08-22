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
    pkg_download_url = "https://pkg.rvsta.sh"
    pkg_upload_url = "https://push.rvsta.sh"
    customer_id = "cus_..."
    customer_unique_id = "a8f3k2mz"
    credential_type = "expiring"
    expires_at = "2026-06-17T16:00:00+00:00"
    refresh_expires_at = "2026-06-17T20:00:00+00:00"

    [profiles.default.registries.pypi]
    default_repo = "_abcdefgh/_m7nk3p4q"

    [profiles.default.registries.npm]
    default_repo = "_abcdefgh/_n4b6v8cx"

    [profiles.default.registries.maven]
    default_repo = "_abcdefgh/_p2q4r6st"
"""

from __future__ import annotations

import os
import re
import tempfile
import tomllib
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import tomli_w

from .paths import rvs_home


RegistryKind = Literal["pypi", "npm", "maven", "container", "helm"]

CONFIG_DIR = rvs_home()
CONFIG_FILE = CONFIG_DIR / "config.toml"
PROFILE_ENV_FILE = CONFIG_DIR / "profiles.env"
LOCAL_ENV_FILE_NAME = ".rvs.env"

DEFAULT_API_URL = "https://api.ravenstash.com"
DEFAULT_PKG_DOWNLOAD_URL = "https://pkg.rvsta.sh"
DEFAULT_PKG_UPLOAD_URL = "https://push.rvsta.sh"


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
    pkg_download_url: str = DEFAULT_PKG_DOWNLOAD_URL
    pkg_upload_url: str = DEFAULT_PKG_UPLOAD_URL
    customer_id: str | None = None
    customer_unique_id: str | None = None
    credential_type: str | None = None
    expires_at: str | None = None
    refresh_expires_at: str | None = None
    registries: dict[RegistryKind, RegistryDefaults] = field(default_factory=dict)


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
    return os.environ.get("RVS_PROFILE") or resolved_cfg.default_profile


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


def profile_pkg_download_url(profile_name: str) -> str:
    return _profile_service_url(
        profile_name,
        suffix="PKG_DOWNLOAD_URL",
        default_env_key="RVS_PKG_DOWNLOAD_URL",
        default_url=DEFAULT_PKG_DOWNLOAD_URL,
    )


def profile_pkg_upload_url(profile_name: str) -> str:
    return _profile_service_url(
        profile_name,
        suffix="PKG_UPLOAD_URL",
        default_env_key="RVS_PKG_UPLOAD_URL",
        default_url=DEFAULT_PKG_UPLOAD_URL,
    )


def _default_profile_config(profile_name: str) -> ProfileConfig:
    return ProfileConfig(
        api_url=profile_api_url(profile_name),
        pkg_download_url=profile_pkg_download_url(profile_name),
        pkg_upload_url=profile_pkg_upload_url(profile_name),
    )


# ── Serialisation helpers ─────────────────────────────────────────────────────


def _load_raw() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with CONFIG_FILE.open("rb") as f:
        return tomllib.load(f)


def load() -> RvsConfig:
    raw = _load_raw()
    cfg = RvsConfig(default_profile=raw.get("default_profile", "default"))

    for name, vals in raw.get("profiles", {}).items():
        cfg.profiles[name] = ProfileConfig(
            api_url=validate_service_url(
                vals.get("api_url", profile_api_url(name)),
                label=f"{name} API URL",
            ),
            pkg_download_url=validate_service_url(
                vals.get("pkg_download_url", profile_pkg_download_url(name)),
                label=f"{name} package download URL",
            ),
            pkg_upload_url=validate_service_url(
                vals.get("pkg_upload_url", profile_pkg_upload_url(name)),
                label=f"{name} package upload URL",
            ),
            customer_id=vals.get("customer_id"),
            customer_unique_id=vals.get("customer_unique_id"),
            credential_type=vals.get("credential_type"),
            expires_at=vals.get("expires_at"),
            refresh_expires_at=vals.get("refresh_expires_at"),
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
    raw: dict = {"default_profile": cfg.default_profile}

    if cfg.profiles:
        raw["profiles"] = {
            name: {
                k: v
                for k, v in {
                    "api_url": p.api_url,
                    "pkg_download_url": p.pkg_download_url,
                    "pkg_upload_url": p.pkg_upload_url,
                    "customer_id": p.customer_id,
                    "customer_unique_id": p.customer_unique_id,
                    "credential_type": p.credential_type,
                    "expires_at": p.expires_at,
                    "refresh_expires_at": p.refresh_expires_at,
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
        pkg_download_url=existing.pkg_download_url,
        pkg_upload_url=existing.pkg_upload_url,
        customer_id=existing.customer_id,
        customer_unique_id=existing.customer_unique_id,
        credential_type=existing.credential_type,
        expires_at=existing.expires_at,
        refresh_expires_at=existing.refresh_expires_at,
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
        pkg_download_url=existing.pkg_download_url,
        pkg_upload_url=existing.pkg_upload_url,
        customer_id=None,
        customer_unique_id=None,
        credential_type=None,
        expires_at=None,
        refresh_expires_at=None,
        registries=existing.registries,
    )
    save(cfg)


def set_profile_metadata(
    profile: str,
    *,
    api_url: str | None = None,
    pkg_download_url: str | None = None,
    pkg_upload_url: str | None = None,
    customer_id: str | None = None,
    customer_unique_id: str | None = None,
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
        pkg_download_url=(
            validate_service_url(
                pkg_download_url,
                label=f"{profile} package download URL",
            )
            if pkg_download_url is not None
            else existing.pkg_download_url
        ),
        pkg_upload_url=(
            validate_service_url(
                pkg_upload_url,
                label=f"{profile} package upload URL",
            )
            if pkg_upload_url is not None
            else existing.pkg_upload_url
        ),
        customer_id=customer_id if customer_id is not None else existing.customer_id,
        customer_unique_id=customer_unique_id
        if customer_unique_id is not None
        else existing.customer_unique_id,
        credential_type=credential_type
        if credential_type is not None
        else existing.credential_type,
        expires_at=expires_at if expires_at is not None else existing.expires_at,
        refresh_expires_at=refresh_expires_at
        if refresh_expires_at is not None
        else existing.refresh_expires_at,
        registries=existing.registries,
    )
    save(cfg)


def set_default_profile(profile: str) -> None:
    cfg = load()
    cfg.default_profile = profile
    save(cfg)


def delete_profile(profile: str) -> bool:
    cfg = load()
    if profile not in cfg.profiles:
        return False

    del cfg.profiles[profile]
    if cfg.default_profile == profile:
        cfg.default_profile = next(iter(cfg.profiles), "default")
    save(cfg)
    return True


def delete_all_profiles() -> None:
    cfg = load()
    cfg.profiles = {}
    cfg.default_profile = "default"
    save(cfg)


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


def mark_registry_default_unavailable(kind: RegistryKind, profile: str | None = None) -> None:
    """Keep an immutable saved target but record that current authority denied it."""
    cfg = load()
    profile_name = profile or current_profile_name(cfg)
    profile_config = cfg.profiles.get(profile_name)
    if profile_config is None or kind not in profile_config.registries:
        return
    profile_config.registries[kind].is_available = False
    save(cfg)
