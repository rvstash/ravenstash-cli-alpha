from __future__ import annotations

from typing import TYPE_CHECKING

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
        "RVS_PKG_API_URL",
        "RVS_PKG_DOWNLOAD_URL",
        "RVS_PKG_UPLOAD_URL",
        "RVS_PROFILE_STAGING_PKG_API_URL",
        "RVS_PROFILE_STAGING_PKG_DOWNLOAD_URL",
        "RVS_PROFILE_STAGING_PKG_UPLOAD_URL",
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
    assert cfg.active_profile().pkg_api_url == "https://app.ravenstash.com/api"
    assert cfg.active_profile().pkg_download_url == "https://pkg.rvsta.sh"
    assert cfg.active_profile().pkg_upload_url == "https://push.rvsta.sh"


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
customer_public_id = "custpid1"
""".strip(),
        encoding="utf-8",
    )

    profile = cfg_mod.load().active_profile()

    assert profile.api_url == "https://staging.example.test"
    assert profile.customer_id == "cus_staging"
    assert profile.customer_public_id == "custpid1"


def test_profile_api_url_can_be_declared_in_gitignored_local_env_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _point_config(monkeypatch, tmp_path)
    (tmp_path / ".rvs.env").write_text(
        """
RVS_PROFILE_STAGING_API_URL=https://staging.example.test
RVS_PROFILE_DEV_API_URL='http://dev.example.test'
""".strip(),
        encoding="utf-8",
    )

    assert cfg_mod.profile_api_url("staging") == "https://staging.example.test"
    assert cfg_mod.profile_api_url("dev") == "http://dev.example.test"


def test_package_service_urls_can_be_declared_per_profile(monkeypatch, tmp_path: Path) -> None:
    _point_config(monkeypatch, tmp_path)
    (tmp_path / ".rvs.env").write_text(
        """
RVS_PROFILE_STAGING_PKG_API_URL=https://app.staging.example.test/api
RVS_PROFILE_STAGING_PKG_DOWNLOAD_URL=https://pkg-staging.example.test
RVS_PROFILE_STAGING_PKG_UPLOAD_URL=https://push-staging.example.test
""".strip(),
        encoding="utf-8",
    )

    profile = cfg_mod.load().active_profile("staging")

    assert profile.pkg_api_url == "https://app.staging.example.test/api"
    assert profile.pkg_download_url == "https://pkg-staging.example.test"
    assert profile.pkg_upload_url == "https://push-staging.example.test"


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
        profiles={
            "work": cfg_mod.ProfileConfig(
                api_url="https://api.work.example",
                pkg_api_url="https://app.work.example/api",
                pkg_download_url="https://pkg-work.example",
                pkg_upload_url="https://pkg-push-work.example",
                customer_id="cus_work",
                customer_public_id="custpid1",
                credential_type="expiring",
                expires_at="2099-01-01T00:00:00+00:00",
                refresh_expires_at="2099-01-02T00:00:00+00:00",
            )
        },
        registries={
            "pypi": cfg_mod.RegistryDefaults(default_repo="repo-pypi"),
            "npm": cfg_mod.RegistryDefaults(default_repo="repo-npm"),
        },
    )

    cfg_mod.save(cfg)
    loaded = cfg_mod.load()

    assert loaded.default_profile == "work"
    assert loaded.profiles["work"].api_url == "https://api.work.example"
    assert loaded.profiles["work"].pkg_api_url == "https://app.work.example/api"
    assert loaded.profiles["work"].pkg_download_url == "https://pkg-work.example"
    assert loaded.profiles["work"].pkg_upload_url == "https://pkg-push-work.example"
    assert loaded.profiles["work"].customer_id == "cus_work"
    assert loaded.profiles["work"].customer_public_id == "custpid1"
    assert loaded.registry_defaults("pypi").default_repo == "repo-pypi"
    assert loaded.registry_defaults("npm").default_repo == "repo-npm"
    assert loaded.registry_defaults("maven").default_repo is None


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
                    customer_public_id="oldpid1",
                    credential_type="expiring",
                )
            }
        )
    )

    cfg_mod.set_profile_metadata("default", customer_id="cus_new")
    profile = cfg_mod.load().profiles["default"]

    assert profile.api_url == "https://api.example"
    assert profile.customer_id == "cus_new"
    assert profile.customer_public_id == "oldpid1"
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


def test_registry_defaults_are_profile_scoped_with_legacy_fallback(
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
            registries={"pypi": cfg_mod.RegistryDefaults(default_repo="legacy")},
        )
    )

    cfg_mod.set_registry_default_repo("pypi", "work-repo", "work")
    cfg_mod.set_registry_default_repo("pypi", "staging-repo", "staging")
    loaded = cfg_mod.load()

    assert loaded.registry_defaults("pypi", "work").default_repo == "work-repo"
    assert loaded.registry_defaults("pypi", "staging").default_repo == "staging-repo"
    assert loaded.registry_defaults("npm", "work").default_repo is None
    assert loaded.registries["pypi"].default_repo == "legacy"
