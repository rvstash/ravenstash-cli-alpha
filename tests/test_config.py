from __future__ import annotations

import os
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
    _config_dir, config_file = _point_config(monkeypatch, tmp_path)

    cfg = cfg_mod.load()

    assert cfg.default_profile == "default"
    assert cfg.profiles == {}
    assert cfg.active_profile().api_url == "https://api.ravenstash.com"
    assert cfg.active_profile("dev").api_url == "https://api.ravenstash.com"
    assert cfg.active_profile("staging").api_url == "https://api.ravenstash.com"
    assert cfg.active_profile().native_registries.pypi.read_base_url == "https://pypi.rvsta.sh"
    assert cfg.active_profile().native_registries.pypi.push_base_url == "https://push.pypi.rvsta.sh"
    assert (
        cfg.active_profile().native_registries.pypi.mirror_base_url
        == "https://mirror.pypi.rvsta.sh"
    )
    assert not config_file.exists()


def test_load_uses_env_api_url_for_configured_profile_without_api_url(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_dir, config_file = _point_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVS_PROFILE_STAGING_API_URL", "https://staging.example.test")
    config_dir.mkdir()
    config_file.write_text(
        """
config_version = 5
default_profile = "staging"

[profiles.staging]
customer_id = "cus_staging"
customer_unique_id = "custpid1"
""".strip(),
        encoding="utf-8",
    )

    profile = cfg_mod.load().active_profile()

    assert profile.api_url == "https://staging.example.test"
    assert profile.customer_id is None
    assert profile.customer_unique_id is None


def test_env_api_url_overrides_saved_profile_url(monkeypatch, tmp_path: Path) -> None:
    config_dir, config_file = _point_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVS_PROFILE_STAGING_API_URL", "https://devapi.staging.example.test")
    config_dir.mkdir()
    config_file.write_text(
        """
config_version = 5
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
RVS_PROFILE_DEV_API_URL='http://localhost:43100'
""".strip(),
        encoding="utf-8",
    )

    assert cfg_mod.profile_api_url("staging") == "https://staging.example.test"
    assert cfg_mod.profile_api_url("dev") == "http://localhost:43100"


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
        "RVS_PROFILE_STAGING_REPOSITORY_DOMAIN=packages.example.test\n",
        encoding="utf-8",
    )

    profile = cfg_mod.load().active_profile("staging")

    assert profile.native_registries.pypi.read_base_url == "https://pypi.packages.example.test"
    assert profile.native_registries.pypi.push_base_url == "https://push.pypi.packages.example.test"
    assert (
        profile.native_registries.pypi.mirror_base_url
        == "https://mirror.pypi.packages.example.test"
    )
    assert profile.native_registries.npm.read_base_url == "https://npm.packages.example.test"
    assert (
        profile.native_registries.maven.push_base_url == "https://push.maven.packages.example.test"
    )
    assert profile.native_registries.oci_registry_base_url == "https://oci.packages.example.test"


@pytest.mark.parametrize(
    "repository_domain",
    ["localhost", "sandbox.localhost", "*.sandbox.localhost"],
)
def test_localhost_repository_domain_uses_literal_host_and_keeps_routes(
    monkeypatch,
    tmp_path: Path,
    repository_domain: str,
) -> None:
    config_dir, config_file = _point_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVS_PROFILE_DEV_REPOSITORY_DOMAIN", repository_domain)
    config_dir.mkdir()
    config_file.write_text(
        """
config_version = 5
[profiles.dev.native_registries.pypi]
read_base_url = "https://download.example.test:43101/registry/pypi"
push_base_url = "https://upload.example.test:43102/registry/pypi"
mirror_base_url = "https://mirror.example.test:43101/registry/pypi"

[profiles.dev.native_registries.npm]
read_base_url = "https://download.example.test:43101/registry/npm"
push_base_url = "https://upload.example.test:43102/registry/npm"
mirror_base_url = "https://mirror.example.test:43101/registry/npm"

[profiles.dev.native_registries.maven]
read_base_url = "https://download.example.test:43101/registry/maven"
push_base_url = "https://upload.example.test:43102/registry/maven"
mirror_base_url = "https://mirror.example.test:43101/registry/maven"

[profiles.dev.native_registries.oci]
registry_base_url = "https://images.example.test:43101"
""".strip(),
        encoding="utf-8",
    )

    endpoints = cfg_mod.load().active_profile("dev").native_registries

    assert endpoints.pypi.read_base_url == "http://localhost:43101/registry/pypi"
    assert endpoints.pypi.push_base_url == "http://localhost:43102/registry/pypi"
    assert endpoints.npm.mirror_base_url == "http://localhost:43101/registry/npm"
    assert endpoints.oci_registry_base_url == "http://localhost:43101"


def test_discovered_heterogeneous_host_family_is_retained_without_domain_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_dir, config_file = _point_config(monkeypatch, tmp_path)
    config_dir.mkdir()
    config_file.write_text(
        """
config_version = 5
[profiles.work.native_registries.pypi]
read_base_url = "https://python-download.example.test"
push_base_url = "https://python-upload.example.test"
mirror_base_url = "https://python-mirror.example.test"

[profiles.work.native_registries.npm]
read_base_url = "https://javascript-download.example.test"
push_base_url = "https://javascript-upload.example.test"
mirror_base_url = "https://javascript-mirror.example.test"

[profiles.work.native_registries.maven]
read_base_url = "https://java-download.example.test"
push_base_url = "https://java-upload.example.test"
mirror_base_url = "https://java-mirror.example.test"

[profiles.work.native_registries.oci]
registry_base_url = "https://images.example.test"
""".strip(),
        encoding="utf-8",
    )

    endpoints = cfg_mod.load().active_profile("work").native_registries

    assert endpoints.pypi.read_base_url == "https://python-download.example.test"
    assert endpoints.pypi.push_base_url == "https://python-upload.example.test"
    assert endpoints.npm.mirror_base_url == "https://javascript-mirror.example.test"
    assert endpoints.oci_registry_base_url == "https://images.example.test"


def test_load_rejects_non_current_config_without_rewriting_it(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_dir, config_file = _point_config(monkeypatch, tmp_path)
    config_dir.mkdir()
    original = 'config_version = 999\ndefault_profile = "default"\n'
    config_file.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported; reconfigure"):
        cfg_mod.load()

    assert config_file.read_text(encoding="utf-8") == original


def test_repository_domain_rejects_urls_and_ports(monkeypatch, tmp_path: Path) -> None:
    _point_config(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "RVS_PROFILE_STAGING_REPOSITORY_DOMAIN",
        "https://packages.example.test:43103",
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

    if os.name != "nt":
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
                        "https://mirror.pypi.work.example",
                    ),
                    npm=cfg_mod.PackageRegistryEndpoints(
                        "https://npm.work.example",
                        "https://push.npm.work.example",
                        "https://mirror.npm.work.example",
                    ),
                    maven=cfg_mod.PackageRegistryEndpoints(
                        "https://maven.work.example",
                        "https://push.maven.work.example",
                        "https://mirror.maven.work.example",
                    ),
                    oci_registry_base_url="https://oci.work.example",
                ),
                customer_id="ac_abcdefgh",
                credential_store="pass",
                credential_type="expiring",
                expires_at="2099-01-01T00:00:00+00:00",
                refresh_expires_at="2099-01-02T00:00:00+00:00",
                registries={
                    "pypi": cfg_mod.RegistryDefaults(default_repo="in_abcdefgh/ar_23456789"),
                    "npm": cfg_mod.RegistryDefaults(default_repo="in_abcdefgh/ar_xyzabcde"),
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
    assert loaded.profiles["work"].customer_id == "ac_abcdefgh"
    assert loaded.profiles["work"].customer_unique_id is None
    assert loaded.profiles["work"].credential_store == "pass"
    assert loaded.registry_defaults("pypi").default_repo == "in_abcdefgh/ar_23456789"
    assert loaded.registry_defaults("npm").default_repo == "in_abcdefgh/ar_xyzabcde"
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
                            default_repo="in_abcdefgh/ar_23456789",
                            repository_unique_ref="ar_23456789",
                            authority_revision=4,
                        )
                    }
                )
            }
        )
    )

    cfg_mod.mark_registry_default_unavailable("pypi")
    saved = cfg_mod.load().registry_defaults("pypi")

    assert saved.default_repo == "in_abcdefgh/ar_23456789"
    assert saved.repository_unique_ref == "ar_23456789"
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
                    customer_id="ac_abcdefgh",
                    credential_type="expiring",
                )
            }
        )
    )

    cfg_mod.set_profile_metadata("default", customer_id="ac_23456789")
    profile = cfg_mod.load().profiles["default"]

    assert profile.api_url == "https://api.example"
    assert profile.customer_id == "ac_23456789"
    assert profile.customer_unique_id is None
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
