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
    credential_type = "temporary"
    expires_at = "2026-06-17T16:00:00+00:00"

    [profiles.dev]
    api_url = "http://localhost:6002"

    [registries.pypi]
    default_repo = "my-pypi"

    [registries.npm]
    default_repo = "my-npm"

    [registries.maven]
    default_repo = "my-maven"
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import tomli_w


RegistryKind = Literal["pypi", "npm", "maven"]

CONFIG_DIR = Path.home() / ".rvn"
CONFIG_FILE = CONFIG_DIR / "config.toml"

DEFAULT_API_URLS: dict[str, str] = {
    "default": "https://api.ravenstash.com",
    "dev": "http://localhost:6002",
    "staging": "https://api.staging-hxa159.ravenstash.com",
}


@dataclass
class ProfileConfig:
    api_url: str = "https://api.ravenstash.com"
    customer_id: str | None = None
    credential_type: str | None = None
    expires_at: str | None = None


@dataclass
class RegistryDefaults:
    default_repo: str | None = None
    api_url: str | None = None  # per-kind API URL override (takes precedence over profile api_url)


@dataclass
class RvnConfig:
    default_profile: str = "default"
    profiles: dict[str, ProfileConfig] = field(default_factory=dict)
    registries: dict[RegistryKind, RegistryDefaults] = field(default_factory=dict)

    def active_profile(self, profile_name: str | None = None) -> ProfileConfig:
        name = profile_name or os.environ.get("RVN_PROFILE") or self.default_profile
        return self.profiles.get(name, ProfileConfig())

    def registry_defaults(self, kind: RegistryKind) -> RegistryDefaults:
        return self.registries.get(kind, RegistryDefaults())


def current_profile_name(cfg: RvnConfig | None = None) -> str:
    """Return the effective active profile name."""
    resolved_cfg = cfg or load()
    return os.environ.get("RVN_PROFILE") or resolved_cfg.default_profile


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
            api_url=vals.get("api_url", "https://api.ravenstash.com"),
            customer_id=vals.get("customer_id"),
            credential_type=vals.get("credential_type"),
            expires_at=vals.get("expires_at"),
        )

    for kind, vals in raw.get("registries", {}).items():
        cfg.registries[kind] = RegistryDefaults(  # type: ignore[index]
            default_repo=vals.get("default_repo"),
            api_url=vals.get("api_url"),
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
                    "api_url": r.api_url,
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
    existing = cfg.profiles.get(profile, ProfileConfig())
    cfg.profiles[profile] = ProfileConfig(
        api_url=api_url if api_url is not None else existing.api_url,
        customer_id=existing.customer_id,
        credential_type=existing.credential_type,
        expires_at=existing.expires_at,
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
    )
    save(cfg)


def set_profile_metadata(
    profile: str,
    *,
    api_url: str | None = None,
    customer_id: str | None = None,
    credential_type: str | None = None,
    expires_at: str | None = None,
) -> None:
    cfg = load()
    existing = cfg.profiles.get(profile, ProfileConfig())
    cfg.profiles[profile] = ProfileConfig(
        api_url=api_url if api_url is not None else existing.api_url,
        customer_id=customer_id if customer_id is not None else existing.customer_id,
        credential_type=credential_type
        if credential_type is not None
        else existing.credential_type,
        expires_at=expires_at if expires_at is not None else existing.expires_at,
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


def set_registry_default_repo(kind: RegistryKind, repo: str, profile: str | None = None) -> None:
    cfg = load()
    existing = cfg.registries.get(kind, RegistryDefaults())
    cfg.registries[kind] = RegistryDefaults(
        default_repo=repo,
        api_url=existing.api_url,
    )
    save(cfg)


def set_registry_override(
    kind: RegistryKind,
    api_url: str | None = None,
    default_repo: str | None = None,
) -> None:
    """Set per-kind registry overrides (api_url or default_repo)."""
    cfg = load()
    existing = cfg.registries.get(kind, RegistryDefaults())
    cfg.registries[kind] = RegistryDefaults(
        default_repo=default_repo if default_repo is not None else existing.default_repo,
        api_url=api_url if api_url is not None else existing.api_url,
    )
    save(cfg)
