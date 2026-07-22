from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from rvs import config as cfg_mod
from rvs.auth import credentials as auth_mod


if TYPE_CHECKING:
    from pathlib import Path


def _isolate_config(monkeypatch, tmp_path: Path, content: str) -> None:
    config_dir = tmp_path / ".rvs"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text(content.strip(), encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)


def test_credential_type_display_keeps_legacy_temporary_user_facing_as_expiring() -> None:
    assert auth_mod.is_refreshable_credential_type("expiring") is True
    assert auth_mod.is_refreshable_credential_type("temporary") is True
    assert auth_mod.is_refreshable_credential_type("token") is False
    assert auth_mod.display_credential_type("temporary") == "expiring"
    assert auth_mod.display_credential_type("expiring") == "expiring"


def test_set_token_requires_keyring(monkeypatch) -> None:
    monkeypatch.setattr(auth_mod, "_keyring_available", lambda: False)

    with pytest.raises(RuntimeError, match="No usable OS keyring"):
        auth_mod.set_token("default", "token")


def test_has_active_expiring_session_requires_valid_refresh_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(
        monkeypatch,
        tmp_path,
        """
default_profile = "default"

[profiles.default]
api_url = "https://api.ravenstash.com"
credential_type = "expiring"
refresh_expires_at = "2099-01-01T00:00:00+00:00"

[profiles.expired]
api_url = "https://api.ravenstash.com"
credential_type = "expiring"
refresh_expires_at = "2000-01-01T00:00:00+00:00"

[profiles.static]
api_url = "https://api.ravenstash.com"
credential_type = "token"
refresh_expires_at = "2099-01-01T00:00:00+00:00"
""",
    )
    monkeypatch.setattr(auth_mod, "_keyring_available", lambda: True)
    monkeypatch.setattr(
        auth_mod,
        "_kr_get",
        lambda profile: "refresh-token" if profile == "default:refresh" else None,
    )

    assert auth_mod.has_active_expiring_session("default") is True
    assert auth_mod.has_active_expiring_session("expired") is False
    assert auth_mod.has_active_expiring_session("static") is False
    assert auth_mod.has_active_expiring_session("missing") is False


def test_delete_token_removes_access_and_refresh_tokens_and_clears_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(
        monkeypatch,
        tmp_path,
        """
default_profile = "default"

[profiles.default]
api_url = "https://api.ravenstash.com"
customer_id = "cus_123"
customer_public_id = "custpid1"
credential_type = "expiring"
expires_at = "2099-01-01T00:00:00+00:00"
refresh_expires_at = "2099-01-02T00:00:00+00:00"
""",
    )
    deleted: list[str] = []
    monkeypatch.setattr(auth_mod, "_kr_delete", lambda profile: deleted.append(profile))

    auth_mod.delete_token("default")
    profile = cfg_mod.load().profiles["default"]

    assert deleted == ["default", "default:refresh"]
    assert profile.api_url == "https://api.ravenstash.com"
    assert profile.pkg_api_url == "https://app.ravenstash.com/api"
    assert profile.pkg_download_url == "https://pkg.rvsta.sh"
    assert profile.pkg_upload_url == "https://push.rvsta.sh"
    assert profile.customer_id is None
    assert profile.customer_public_id is None
    assert profile.credential_type is None
    assert profile.expires_at is None
    assert profile.refresh_expires_at is None


def test_get_refresh_token_returns_none_when_keyring_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(auth_mod, "_keyring_available", lambda: False)

    assert auth_mod.get_refresh_token("default") is None
