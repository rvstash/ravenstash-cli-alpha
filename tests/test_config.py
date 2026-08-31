from __future__ import annotations

import stat
from typing import TYPE_CHECKING

import pytest
from rvs import config as cfg_mod


if TYPE_CHECKING:
    from pathlib import Path


def _point_config(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    config_dir = tmp_path / ".rvs"
    config_file = config_dir / "config.toml"
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(cfg_mod, "PROFILE_ENV_FILE", config_dir / "profiles.env")
    monkeypatch.chdir(tmp_path)
    for key in (
        "RVS_API_URL",
        "RVS_ENV_FILE",
        "RVS_PROFILE_DEV_API_URL",
        "RVS_PROFILE_STAGING_API_URL",
        "RVS_REPOSITORY_DOMAIN",
        "RVS_PROFILE_DEV_REPOSITORY_DOMAIN",
        "RVS_PROFILE_STAGING_REPOSITORY_DOMAIN",
        "RVS_PKG_API_URL",
        "RVS_PROFILE_STAGING_PKG_API_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    return config_dir, config_file


def test_load_missing_config_uses_production_default_without_profile_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _point_config(monkeypatch, tmp_path)

    cfg = cfg_mod.load()

    assert cfg.default_profile == "default"
    assert cfg.profiles == {}
    assert cfg.active_profile().api_url == "https://api.ravenstash.com"
    assert cfg.active_profile("dev").api_url == "https://api.ravenstash.com"
    assert cfg.active_profile("staging").api_url == "https://api.ravenstash.com"
    assert cfg.active_profile().native_registries.pypi.read_base_url == "https://pypi.rvsta.sh"
    assert cfg.active_profile().native_registries.pypi.push_base_url == "https://push.pypi.rvsta.sh"
    assert (
        cfg.active_profile().native_registries.pypi.cache_base_url == "https://cache.pypi.rvsta.sh"
    )


def test_load_uses_env_api_url_for_configured_profile_without_api_url(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_dir, config_file = _point_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVS_PROFILE_STAGING_API_URL", "https://staging.example.test")
    config_dir.mkdir()
    config_file.write_text(
        """
default_profile = "staging"

[profiles.staging]
customer_id = "cus_staging"
customer_unique_id = "custpid1"
""".strip(),
        encoding="utf-8",
    )

    profile = cfg_mod.load().active_profile()

    assert profile.api_url == "https://staging.example.test"
    assert profile.customer_id == "cus_staging"
    assert profile.customer_unique_id == "custpid1"


def test_env_api_url_overrides_saved_profile_url(monkeypatch, tmp_path: Path) -> None:
    config_dir, config_file = _point_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVS_PROFILE_STAGING_API_URL", "https://devapi.staging.example.test")
    config_dir.mkdir()
    config_file.write_text(
        """
[profiles.staging]
api_url = "https://api.ravenstash.com"
""".strip(),
        encoding="utf-8",
    )

    assert cfg_mod.load().active_profile("staging").api_url == "https://devapi.staging.example.test"


def test_profile_api_url_can_be_declared_in_gitignored_local_env_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _point_config(monkeypatch, tmp_path)
    (tmp_path / ".rvs.env").write_text(
        """
RVS_PROFILE_STAGING_API_URL=https://staging.example.test
RVS_PROFILE_DEV_API_URL='http://localhost:8000'
""".strip(),
        encoding="utf-8",
    )

    assert cfg_mod.profile_api_url("staging") == "https://staging.example.test"
    assert cfg_mod.profile_api_url("dev") == "http://localhost:8000"


def test_profile_api_url_rejects_non_loopback_plain_http(monkeypatch, tmp_path: Path) -> None:
    _point_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVS_PROFILE_DEV_API_URL", "http://dev.example.test")

    with pytest.raises(ValueError, match="must use HTTPS"):
        cfg_mod.profile_api_url("dev")


def test_repository_domain_formats_every_registry_service_for_profile(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _point_config(monkeypatch, tmp_path)
    (tmp_path / ".rvs.env").write_text(
        "RVS_PROFILE_STAGING_REPOSITORY_DOMAIN=packages.staging.example.test\n",
        encoding="utf-8",
    )

    profile = cfg_mod.load().active_profile("staging")

    assert (
        profile.native_registries.pypi.read_base_url == "https://pypi.packages.staging.example.test"
    )
    assert (
        profile.native_registries.pypi.push_base_url
        == "https://push.pypi.packages.staging.example.test"
    )
    assert (
        profile.native_registries.pypi.cache_base_url
        == "https://cache.pypi.packages.staging.example.test"
    )
    assert (
        profile.native_registries.npm.read_base_url == "https://npm.packages.staging.example.test"
    )
    assert (
        profile.native_registries.maven.push_base_url
        == "https://push.maven.packages.staging.example.test"
    )
    assert (
        profile.native_registries.oci_registry_base_url
        == "https://oci.packages.staging.example.test"
    )


def test_repository_domain_override_rewrites_discovered_hosts_but_keeps_routes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_dir, config_file = _point_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVS_PROFILE_DEV_REPOSITORY_DOMAIN", "*.dev.localhost")
    config_dir.mkdir()
    config_file.write_text(
        """
[profiles.dev.native_registries.pypi]
read_base_url = "http://localhost:8788/native/pypi"
push_base_url = "http://localhost:6001/native/pypi"
cache_base_url = "http://localhost:8788/native/pypi"

[profiles.dev.native_registries.npm]
read_base_url = "http://localhost:8788/native/npm"
push_base_url = "http://localhost:6001/native/npm"
cache_base_url = "http://localhost:8788/native/npm"

[profiles.dev.native_registries.maven]
read_base_url = "http://localhost:8788/native/maven"
push_base_url = "http://localhost:6001/native/maven"
cache_base_url = "http://localhost:8788/native/maven"

[profiles.dev.native_registries.oci]
registry_base_url = "http://localhost:8788"
""".strip(),
        encoding="utf-8",
    )

    endpoints = cfg_mod.load().active_profile("dev").native_registries

    assert endpoints.pypi.read_base_url == "http://pypi.dev.localhost:8788/native/pypi"
    assert endpoints.pypi.push_base_url == "http://push.pypi.dev.localhost:6001/native/pypi"
    assert endpoints.npm.cache_base_url == "http://cache.npm.dev.localhost:8788/native/npm"
    assert endpoints.oci_registry_base_url == "http://oci.dev.localhost:8788"


def test_discovered_non_suffix_host_family_is_retained_without_domain_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_dir, config_file = _point_config(monkeypatch, tmp_path)
    config_dir.mkdir()
    config_file.write_text(
        """
[profiles.staging.native_registries.pypi]
read_base_url = "https://pypi-staging-hxa159.rvsta.sh"
push_base_url = "https://push.pypi-staging-hxa159.rvsta.sh"
cache_base_url = "https://cache.pypi-staging-hxa159.rvsta.sh"

[profiles.staging.native_registries.npm]
read_base_url = "https://npm-staging-hxa159.rvsta.sh"
push_base_url = "https://push.npm-staging-hxa159.rvsta.sh"
cache_base_url = "https://cache.npm-staging-hxa159.rvsta.sh"

[profiles.staging.native_registries.maven]
read_base_url = "https://maven-staging-hxa159.rvsta.sh"
push_base_url = "https://push.maven-staging-hxa159.rvsta.sh"
cache_base_url = "https://cache.maven-staging-hxa159.rvsta.sh"

[profiles.staging.native_registries.oci]
registry_base_url = "https://oci-staging-hxa159.rvsta.sh"
""".strip(),
        encoding="utf-8",
    )

    endpoints = cfg_mod.load().active_profile("staging").native_registries

    assert endpoints.pypi.read_base_url == "https://pypi-staging-hxa159.rvsta.sh"
    assert endpoints.pypi.push_base_url == "https://push.pypi-staging-hxa159.rvsta.sh"
    assert endpoints.npm.cache_base_url == "https://cache.npm-staging-hxa159.rvsta.sh"
    assert endpoints.oci_registry_base_url == "https://oci-staging-hxa159.rvsta.sh"


def test_repository_domain_rejects_urls_and_ports(monkeypatch, tmp_path: Path) -> None:
    _point_config(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "RVS_PROFILE_STAGING_REPOSITORY_DOMAIN",
        "https://packages.staging.example.test:8443",
    )

    with pytest.raises(ValueError, match="without a scheme, port, or path"):
        cfg_mod.load().active_profile("staging")


def test_explicit_rvs_env_file_overrides_local_env_file(monkeypatch, tmp_path: Path) -> None:
    _point_config(monkeypatch, tmp_path)
    (tmp_path / ".rvs.env").write_text(
        "RVS_PROFILE_STAGING_API_URL=https://local.example.test\n",
        encoding="utf-8",
    )
    explicit_env_file = tmp_path / "explicit.env"
    explicit_env_file.write_text(
        "export RVS_PROFILE_STAGING_API_URL=https://explicit.example.test\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RVS_ENV_FILE", str(explicit_env_file))

    assert cfg_mod.profile_api_url("staging") == "https://explicit.example.test"


def test_save_uses_private_modes_and_atomic_replacement(monkeypatch, tmp_path: Path) -> None:
    config_dir, config_file = _point_config(monkeypatch, tmp_path)
    cfg = cfg_mod.RvsConfig(
        profiles={"default": cfg_mod.ProfileConfig()},
    )

    cfg_mod.save(cfg)
    first_inode = config_file.stat().st_ino
    cfg.default_profile = "work"
    cfg_mod.save(cfg)

    assert stat.S_IMODE(config_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(config_file.stat().st_mode) == 0o600
    assert config_file.stat().st_ino != first_inode
    assert not list(config_dir.glob(".config.*.tmp"))


def test_process_env_overrides_env_files(monkeypatch, tmp_path: Path) -> None:
    _point_config(monkeypatch, tmp_path)
    (tmp_path / ".rvs.env").write_text(
        "RVS_PROFILE_STAGING_API_URL=https://local.example.test\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RVS_PROFILE_STAGING_API_URL", "https://process.example.test")

    assert cfg_mod.profile_api_url("staging") == "https://process.example.test"


def test_save_and_load_round_trips_profiles_and_registry_defaults(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _point_config(monkeypatch, tmp_path)
    cfg = cfg_mod.RvsConfig(
        default_profile="work",
        credential_store="pass",
        profiles={
            "work": cfg_mod.ProfileConfig(
                api_url="https://api.work.example",
                native_registries=cfg_mod.NativeRegistryEndpoints(
                    pypi=cfg_mod.PackageRegistryEndpoints(
                        "https://pypi.work.example",
                        "https://push.pypi.work.example",
                        "https://cache.pypi.work.example",
                    ),
                    npm=cfg_mod.PackageRegistryEndpoints(
                        "https://npm.work.example",
                        "https://push.npm.work.example",
                        "https://cache.npm.work.example",
                    ),
                    maven=cfg_mod.PackageRegistryEndpoints(
                        "https://maven.work.example",
                        "https://push.maven.work.example",
                        "https://cache.maven.work.example",
                    ),
                    oci_registry_base_url="https://oci.work.example",
                ),
                customer_id="cus_work",
                customer_unique_id="custpid1",
                credential_store="pass",
                credential_type="expiring",
                expires_at="2099-01-01T00:00:00+00:00",
                refresh_expires_at="2099-01-02T00:00:00+00:00",
                registries={
                    "pypi": cfg_mod.RegistryDefaults(default_repo="_abcdefgh/_pypi0001"),
                    "npm": cfg_mod.RegistryDefaults(default_repo="_abcdefgh/_npm00001"),
                },
            )
        },
    )

    cfg_mod.save(cfg)
    loaded = cfg_mod.load()

    assert loaded.default_profile == "work"
    assert loaded.credential_store == "pass"
    assert loaded.profiles["work"].api_url == "https://api.work.example"
    assert (
        loaded.profiles["work"].native_registries.pypi.read_base_url == "https://pypi.work.example"
    )
    assert (
        loaded.profiles["work"].native_registries.npm.push_base_url
        == "https://push.npm.work.example"
    )
    assert (
        loaded.profiles["work"].native_registries.oci_registry_base_url
        == "https://oci.work.example"
    )
    assert loaded.profiles["work"].customer_id == "cus_work"
    assert loaded.profiles["work"].customer_unique_id == "custpid1"
    assert loaded.profiles["work"].credential_store == "pass"
    assert loaded.registry_defaults("pypi").default_repo == "_abcdefgh/_pypi0001"
    assert loaded.registry_defaults("npm").default_repo == "_abcdefgh/_npm00001"
    assert loaded.registry_defaults("maven").default_repo is None


def test_saved_target_retains_identity_when_authority_marks_it_unavailable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _point_config(monkeypatch, tmp_path)
    cfg_mod.save(
        cfg_mod.RvsConfig(
            profiles={
                "default": cfg_mod.ProfileConfig(
                    registries={
                        "pypi": cfg_mod.RegistryDefaults(
                            default_repo="_abcdefgh/_pypi0001",
                            repository_id="repository-1",
                            authority_revision=4,
                        )
                    }
                )
            }
        )
    )

    cfg_mod.mark_registry_default_unavailable("pypi")
    saved = cfg_mod.load().registry_defaults("pypi")

    assert saved.default_repo == "_abcdefgh/_pypi0001"
    assert saved.repository_id == "repository-1"
    assert saved.authority_revision == 4
    assert saved.is_available is False


def test_current_profile_name_prefers_environment(monkeypatch) -> None:
    monkeypatch.setenv("RVS_PROFILE", "staging")

    assert cfg_mod.current_profile_name(cfg_mod.RvsConfig(default_profile="work")) == "staging"


def test_set_profile_metadata_preserves_existing_values(monkeypatch, tmp_path: Path) -> None:
    _point_config(monkeypatch, tmp_path)
    cfg_mod.save(
        cfg_mod.RvsConfig(
            profiles={
                "default": cfg_mod.ProfileConfig(
                    api_url="https://api.example",
                    customer_id="cus_old",
                    customer_unique_id="oldpid1",
                    credential_type="expiring",
                )
            }
        )
    )

    cfg_mod.set_profile_metadata("default", customer_id="cus_new")
    profile = cfg_mod.load().profiles["default"]

    assert profile.api_url == "https://api.example"
    assert profile.customer_id == "cus_new"
    assert profile.customer_unique_id == "oldpid1"
    assert profile.credential_type == "expiring"


def test_delete_profile_updates_default_profile(monkeypatch, tmp_path: Path) -> None:
    _point_config(monkeypatch, tmp_path)
    cfg_mod.save(
        cfg_mod.RvsConfig(
            default_profile="work",
            profiles={
                "default": cfg_mod.ProfileConfig(),
                "work": cfg_mod.ProfileConfig(api_url="https://api.work.example"),
            },
        )
    )

    assert cfg_mod.delete_profile("work") is True
    loaded = cfg_mod.load()

    assert "work" not in loaded.profiles
    assert loaded.default_profile == "default"
    assert cfg_mod.delete_profile("missing") is False


def test_registry_defaults_are_profile_scoped(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _point_config(monkeypatch, tmp_path)
    cfg_mod.save(
        cfg_mod.RvsConfig(
            default_profile="work",
            profiles={
                "work": cfg_mod.ProfileConfig(),
                "staging": cfg_mod.ProfileConfig(),
            },
        )
    )

    cfg_mod.set_registry_default_repo("pypi", "work-repo", "work")
    cfg_mod.set_registry_default_repo("pypi", "staging-repo", "staging")
    loaded = cfg_mod.load()

    assert loaded.registry_defaults("pypi", "work").default_repo == "work-repo"
    assert loaded.registry_defaults("pypi", "staging").default_repo == "staging-repo"
    assert loaded.registry_defaults("npm", "work").default_repo is None
