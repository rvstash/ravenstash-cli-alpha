from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rvn import config as cfg_mod
from rvn.auth import commands as auth_cmd
from typer.testing import CliRunner


if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()
STAGING_API_URL = "https://staging.example.test"


def _write_config(config_dir: Path, content: str) -> Path:
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text(content.strip(), encoding="utf-8")
    return config_file


def _isolate_config(monkeypatch, tmp_path: Path, content: str) -> None:
    config_dir = tmp_path / ".rvn"
    config_file = _write_config(config_dir, content)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(cfg_mod, "PROFILE_ENV_FILE", config_dir / "profiles.env")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RVN_ENV_FILE", raising=False)
    monkeypatch.delenv("RVN_PROFILE_STAGING_API_URL", raising=False)


def test_auth_status_reports_env_token_for_builtin_staging_profile(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path, 'default_profile = "default"')
    monkeypatch.setenv("RVN_TOKEN", "env-token")
    monkeypatch.setenv("RVN_PROFILE_STAGING_API_URL", STAGING_API_URL)

    result = runner.invoke(auth_cmd.app, ["status", "--profile", "staging"])

    assert result.exit_code == 0
    assert "staging" in result.output
    assert STAGING_API_URL in result.output
    assert "Authenticated" in result.output
    assert "yes" in result.output
    assert "RVN_TOKEN" in result.output


def test_auth_status_exits_one_when_profile_has_no_token(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path, 'default_profile = "default"')
    monkeypatch.delenv("RVN_TOKEN", raising=False)
    monkeypatch.setenv("RVN_PROFILE_STAGING_API_URL", STAGING_API_URL)
    monkeypatch.setattr(auth_cmd.auth_mod, "get_token", lambda profile: None)
    monkeypatch.setattr(auth_cmd.auth_mod, "token_source", lambda profile: None)

    result = runner.invoke(auth_cmd.app, ["status", "--profile", "staging"])

    assert result.exit_code == 1
    assert "Authenticated" in result.output
    assert "no" in result.output
    assert STAGING_API_URL in result.output


def test_auth_whoami_reads_local_profile_metadata(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(
        monkeypatch,
        tmp_path,
        """
default_profile = "work"

[profiles.work]
api_url = "https://api.work.example"
customer_id = "cus_work"
""",
    )

    result = runner.invoke(auth_cmd.app, ["whoami"])

    assert result.exit_code == 0
    assert "work" in result.output
    assert "cus_work" in result.output
    assert "https://api.work.example" in result.output


def test_auth_login_delegates_to_device_login_with_active_profile(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(
        monkeypatch,
        tmp_path,
        """
default_profile = "work"

[profiles.work]
api_url = "https://api.work.example"
""",
    )
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        auth_cmd,
        "perform_device_login",
        lambda **kwargs: calls.append(kwargs),
    )

    result = runner.invoke(
        auth_cmd.app,
        ["login", "--api-url", "https://api.override.example", "--duration", "8h", "--no-browser"],
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "profile": "work",
            "api_url": "https://api.override.example",
            "no_browser": True,
            "duration": "8h",
        }
    ]


def test_auth_profile_list_reports_no_profiles(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path, 'default_profile = "default"')

    result = runner.invoke(auth_cmd.app, ["profile", "list"])

    assert result.exit_code == 0
    assert "No profiles configured" in result.output


def test_auth_profile_rename_moves_metadata_and_deletes_old_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(
        monkeypatch,
        tmp_path,
        """
default_profile = "work"

[profiles.work]
api_url = "https://api.work.example"
customer_id = "cus_work"
""",
    )
    deleted: list[str] = []
    monkeypatch.setattr(auth_cmd.auth_mod, "delete_token", lambda profile: deleted.append(profile))

    result = runner.invoke(auth_cmd.app, ["profile", "rename", "work", "staging"])
    cfg = cfg_mod.load()

    assert result.exit_code == 0
    assert deleted == ["work"]
    assert "work" not in cfg.profiles
    assert cfg.profiles["staging"].customer_id == "cus_work"
    assert cfg.default_profile == "staging"
    assert "renamed to 'staging'" in result.output


def test_auth_profile_switch_rejects_missing_profile(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(
        monkeypatch,
        tmp_path,
        """
default_profile = "default"

[profiles.default]
api_url = "https://api.ravenstash.com"
""",
    )

    result = runner.invoke(auth_cmd.app, ["profile", "switch", "missing"])

    assert result.exit_code == 1
    assert "Profile 'missing' is not configured" in result.stderr


def test_auth_logout_rejects_profile_and_all_together() -> None:
    result = runner.invoke(auth_cmd.app, ["logout", "--profile", "work", "--all"])

    assert result.exit_code == 1
    assert "Use either `--profile` or `--all`, not both" in result.stderr
