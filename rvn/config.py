"""Config file management for rvn.

Config lives at ~/.rvn/config.toml and supports multiple named profiles.
The active profile is resolved by:
  1. --profile CLI flag  (highest priority)
  2. RVN_PROFILE environment variable
  3. default_profile key in config file  (default: "default")

Config file shape
-----------------
::

    default_profile = "default"

    [profiles.default]
    api_url = "https://api.ravenstash.com"
    customer_id = "cus_..."
    credential_type = "expiring"
    expires_at = "2026-06-17T16:00:00+00:00"
    refresh_expires_at = "2026-06-17T20:00:00+00:00"

    [registries.pypi]
    default_repo = "repo_..."

    [registries.npm]
    default_repo = "repo_..."

    [registries.maven]
    default_repo = "repo_..."
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import tomli_w


RegistryKind = Literal["pypi", "npm", "maven"]

CONFIG_DIR = Path.home() / ".rvn"
CONFIG_FILE = CONFIG_DIR / "config.toml"
PROFILE_ENV_FILE = CONFIG_DIR / "profiles.env"
LOCAL_ENV_FILE_NAME = ".rvn.env"

DEFAULT_API_URL = "https://api.ravenstash.com"


@dataclass
class ProfileConfig:
    api_url: str = DEFAULT_API_URL
    customer_id: str | None = None
    credential_type: str | None = None
    expires_at: str | None = None
    refresh_expires_at: str | None = None


@dataclass
class RegistryDefaults:
    default_repo: str | None = None


@dataclass
class RvnConfig:
    default_profile: str = "default"
    profiles: dict[str, ProfileConfig] = field(default_factory=dict)
    registries: dict[RegistryKind, RegistryDefaults] = field(default_factory=dict)

    def active_profile(self, profile_name: str | None = None) -> ProfileConfig:
        name = profile_name or os.environ.get("RVN_PROFILE") or self.default_profile
        return self.profiles.get(name, _default_profile_config(name))

    def registry_defaults(self, kind: RegistryKind) -> RegistryDefaults:
        return self.registries.get(kind, RegistryDefaults())


def current_profile_name(cfg: RvnConfig | None = None) -> str:
    """Return the effective active profile name."""
    resolved_cfg = cfg or load()
    return os.environ.get("RVN_PROFILE") or resolved_cfg.default_profile


# ── Environment helpers ───────────────────────────────────────────────────────


def _profile_env_key(profile_name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", profile_name).strip("_").upper()
    return f"RVN_PROFILE_{normalized}_API_URL"


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
    explicit_env_file = os.environ.get("RVN_ENV_FILE")
    if explicit_env_file:
        values.update(_read_env_file(Path(explicit_env_file).expanduser()))
    return values


def _env_value(name: str) -> str | None:
    return os.environ.get(name) or _env_file_values().get(name)


def profile_api_url(profile_name: str) -> str:
    """Return the default API URL for *profile_name* from env/config defaults."""
    keys = [_profile_env_key(profile_name)]
    if profile_name == "default":
        keys.append("RVN_API_URL")
    for key in keys:
        value = _env_value(key)
        if value:
            return value.rstrip("/")
    return DEFAULT_API_URL


def _default_profile_config(profile_name: str) -> ProfileConfig:
    return ProfileConfig(api_url=profile_api_url(profile_name))


# ── Serialisation helpers ─────────────────────────────────────────────────────


def _load_raw() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with CONFIG_FILE.open("rb") as f:
        return tomllib.load(f)


def load() -> RvnConfig:
    raw = _load_raw()
    cfg = RvnConfig(default_profile=raw.get("default_profile", "default"))

    for name, vals in raw.get("profiles", {}).items():
        cfg.profiles[name] = ProfileConfig(
            api_url=vals.get("api_url", profile_api_url(name)),
            customer_id=vals.get("customer_id"),
            credential_type=vals.get("credential_type"),
            expires_at=vals.get("expires_at"),
            refresh_expires_at=vals.get("refresh_expires_at"),
        )

    for kind, vals in raw.get("registries", {}).items():
        cfg.registries[kind] = RegistryDefaults(  # type: ignore[index]
            default_repo=vals.get("default_repo"),
        )

    return cfg


def save(cfg: RvnConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    raw: dict = {"default_profile": cfg.default_profile}

    if cfg.profiles:
        raw["profiles"] = {
            name: {
                k: v
                for k, v in {
                    "api_url": p.api_url,
                    "customer_id": p.customer_id,
                    "credential_type": p.credential_type,
                    "expires_at": p.expires_at,
                    "refresh_expires_at": p.refresh_expires_at,
                }.items()
                if v is not None
            }
            for name, p in cfg.profiles.items()
        }

    if cfg.registries:
        raw["registries"] = {
            kind: {
                k: v
                for k, v in {
                    "default_repo": r.default_repo,
                }.items()
                if v is not None
            }
            for kind, r in cfg.registries.items()
        }

    with CONFIG_FILE.open("wb") as f:
        tomli_w.dump(raw, f)


# ── Convenience setters ───────────────────────────────────────────────────────


def set_profile_value(profile: str, api_url: str | None = None) -> None:
    cfg = load()
    existing = cfg.profiles.get(profile, _default_profile_config(profile))
    cfg.profiles[profile] = ProfileConfig(
        api_url=api_url if api_url is not None else existing.api_url,
        customer_id=existing.customer_id,
        credential_type=existing.credential_type,
        expires_at=existing.expires_at,
        refresh_expires_at=existing.refresh_expires_at,
    )
    save(cfg)


def clear_profile_credential_metadata(profile: str) -> None:
    cfg = load()
    existing = cfg.profiles.get(profile)
    if existing is None:
        return
    cfg.profiles[profile] = ProfileConfig(
        api_url=existing.api_url,
        customer_id=None,
        credential_type=None,
        expires_at=None,
        refresh_expires_at=None,
    )
    save(cfg)


def set_profile_metadata(
    profile: str,
    *,
    api_url: str | None = None,
    customer_id: str | None = None,
    credential_type: str | None = None,
    expires_at: str | None = None,
    refresh_expires_at: str | None = None,
) -> None:
    cfg = load()
    existing = cfg.profiles.get(profile, _default_profile_config(profile))
    cfg.profiles[profile] = ProfileConfig(
        api_url=api_url if api_url is not None else existing.api_url,
        customer_id=customer_id if customer_id is not None else existing.customer_id,
        credential_type=credential_type
        if credential_type is not None
        else existing.credential_type,
        expires_at=expires_at if expires_at is not None else existing.expires_at,
        refresh_expires_at=refresh_expires_at
        if refresh_expires_at is not None
        else existing.refresh_expires_at,
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


def set_registry_default_repo(kind: RegistryKind, repo: str) -> None:
    cfg = load()
    cfg.registries[kind] = RegistryDefaults(default_repo=repo)
    save(cfg)
