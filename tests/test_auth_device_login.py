from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar
from unittest.mock import ANY
from uuid import UUID

import pytest
from typer.testing import CliRunner


if TYPE_CHECKING:
    from pathlib import Path

from rvs import config as cfg_mod
from rvs.auth import commands as auth_cmd
from rvs.auth import credentials as auth_mod
from rvs.auth import device as login_mod


runner = CliRunner()

NATIVE_REGISTRIES = {
    "pypi": {
        "read_base_url": "https://pypi.rvsta.sh",
        "push_base_url": "https://push.pypi.rvsta.sh",
        "mirror_base_url": "https://mirror.pypi.rvsta.sh",
    },
    "npm": {
        "read_base_url": "https://npm.rvsta.sh",
        "push_base_url": "https://push.npm.rvsta.sh",
        "mirror_base_url": "https://mirror.npm.rvsta.sh",
    },
    "maven": {
        "read_base_url": "https://maven.rvsta.sh",
        "push_base_url": "https://push.maven.rvsta.sh",
        "mirror_base_url": "https://mirror.maven.rvsta.sh",
    },
    "oci": {"registry_base_url": "https://oci.rvsta.sh"},
}


class _FakeStdin:
    def __init__(self, value: str) -> None:
        self._chars = list(value)

    def read(self, size: int) -> str:
        del size
        if not self._chars:
            return ""
        return self._chars.pop(0)

    @property
    def has_pending(self) -> bool:
        return bool(self._chars)


class _FakeFdStdin:
    def fileno(self) -> int:
        return 0

    def read(self, _size: int) -> str:
        raise AssertionError("selector should use os.read for real stdin fds")


def _write_profiles_config(
    config_dir: Path,
    default_profile: str = "default",
    refresh_expires_at: str = "2099-01-01T04:00:00+00:00",
    credential_type: str = "expiring",
) -> None:
    config_file = config_dir / "config.toml"
    config_dir.mkdir()
    config_file.write_text(
        f"""
config_version = 5
default_profile = "{default_profile}"

[profiles.default]
api_url = "https://api.ravenstash.com"
account_ref = "ac_23456789"
credential_type = "{credential_type}"
expires_at = "2099-01-01T00:00:00+00:00"
refresh_expires_at = "{refresh_expires_at}"

[profiles.work]
api_url = "https://api.work.example"
account_ref = "ac_3456789a"
credential_type = "{credential_type}"
expires_at = "2099-01-01T00:00:00+00:00"
refresh_expires_at = "{refresh_expires_at}"
""".strip(),
        encoding="utf-8",
    )


def test_rvs_token_takes_precedence_over_keyring(monkeypatch) -> None:
    monkeypatch.setenv("RVS_TOKEN", "rvs_ust" + "A" * 43)
    monkeypatch.setattr(auth_mod, "_keyring_available", lambda: True)
    monkeypatch.setattr(auth_mod, "_kr_get", lambda profile: "keyring-token")

    assert auth_mod.get_token("default") == "rvs_ust" + "A" * 43
    assert auth_mod.token_source("default") == "RVS_TOKEN"


def test_rvs_token_prevents_expiring_refresh_attempt(monkeypatch) -> None:
    refreshed: list[str] = []

    monkeypatch.setenv("RVS_TOKEN", "rvs_ust" + "A" * 43)
    monkeypatch.setattr(auth_mod, "_stored_profile_expired", lambda profile: True)
    monkeypatch.setattr(
        auth_mod,
        "refresh_expiring_credential",
        lambda profile: refreshed.append(profile) or "refreshed-token",
    )

    assert auth_mod.get_token("default") == "rvs_ust" + "A" * 43
    assert refreshed == []


def test_config_token_is_ignored(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvs"
    config_file = config_dir / "config.toml"
    config_dir.mkdir()
    config_file.write_text(
        """
config_version = 5
default_profile = "default"

[profiles.default]
api_url = "https://api.ravenstash.com"
token = "rvs_tok_old"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)
    monkeypatch.delenv("RVS_TOKEN", raising=False)
    monkeypatch.setattr(auth_mod, "_keyring_available", lambda: False)

    assert auth_mod.get_token("default") is None
    assert auth_mod.token_source("default") is None


def test_staging_profile_uses_env_api_url_when_not_configured(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvs"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text('config_version = 5\ndefault_profile = "default"\n', encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(cfg_mod, "PROFILE_ENV_FILE", config_dir / "profiles.env")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RVS_PROFILE_STAGING_API_URL", "https://staging.example.test")

    assert cfg_mod.load().active_profile("staging").api_url == "https://staging.example.test"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12h", 12 * 60 * 60),
        ("24hour", 24 * 60 * 60),
        ("36hours", 36 * 60 * 60),
        ("1d", 24 * 60 * 60),
        ("5day", 5 * 24 * 60 * 60),
        ("3days", 3 * 24 * 60 * 60),
        ("1month", 30 * 24 * 60 * 60),
        ("2 months", 60 * 24 * 60 * 60),
        ("6months", 180 * 24 * 60 * 60),
    ],
)
def test_parse_duration_seconds(raw: str, expected: int) -> None:
    assert login_mod.parse_duration_seconds(raw) == expected


@pytest.mark.parametrize("raw", ["59m", "0h", "11hours", "181days", "1year", "abc"])
def test_parse_duration_seconds_rejects_out_of_range_or_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        login_mod.parse_duration_seconds(raw)


def test_profile_use_sets_default_profile(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvs"
    _write_profiles_config(config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_dir / "config.toml")

    result = runner.invoke(auth_cmd.profile_app, ["use", "work"])

    assert result.exit_code == 0
    assert cfg_mod.load().default_profile == "work"
    assert "Local profile 'work' selected for persisted default." in result.output


@pytest.mark.parametrize(
    ("sequence", "expected"),
    [
        ("\x1b[A", auth_cmd._KEY_UP),
        ("\x1b[B", auth_cmd._KEY_DOWN),
        ("\x1bOA", auth_cmd._KEY_UP),
        ("\x1bOB", auth_cmd._KEY_DOWN),
        ("\x1b[1;5A", auth_cmd._KEY_UP),
        ("\x1b[1;5B", auth_cmd._KEY_DOWN),
    ],
)
def test_auth_switch_reads_arrow_key_sequences(
    monkeypatch,
    sequence: str,
    expected: str,
) -> None:
    import select as select_mod

    fake_stdin = _FakeStdin(sequence)

    def fake_select(
        readers: list[Any], *_args: Any, **_kwargs: Any
    ) -> tuple[list[Any], list[Any], list[Any]]:
        return (readers if fake_stdin.has_pending else [], [], [])

    monkeypatch.setattr(auth_cmd.sys, "platform", "linux")
    monkeypatch.setattr(auth_cmd.sys, "stdin", fake_stdin)
    monkeypatch.setattr(select_mod, "select", fake_select)

    assert auth_cmd._read_selector_key() == expected


def test_auth_switch_reads_arrow_key_sequences_from_unbuffered_fd(monkeypatch) -> None:
    import select as select_mod

    pending = list(b"\x1b[B")

    def fake_os_read(fd: int, size: int) -> bytes:
        assert fd == 0
        assert size == 1
        if not pending:
            return b""
        return bytes([pending.pop(0)])

    def fake_select(
        readers: list[Any], *_args: Any, **_kwargs: Any
    ) -> tuple[list[Any], list[Any], list[Any]]:
        assert readers == [0]
        return (readers if pending else [], [], [])

    monkeypatch.setattr(auth_cmd.sys, "platform", "linux")
    monkeypatch.setattr(auth_cmd.sys, "stdin", _FakeFdStdin())
    monkeypatch.setattr(auth_cmd.os, "read", fake_os_read)
    monkeypatch.setattr(select_mod, "select", fake_select)

    assert auth_cmd._read_selector_key() == auth_cmd._KEY_DOWN


def test_auth_logout_uses_current_profile(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvs"
    _write_profiles_config(config_dir, default_profile="work")
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_dir / "config.toml")
    deleted: list[str] = []
    monkeypatch.setattr(auth_cmd.auth_mod, "delete_token", lambda profile: deleted.append(profile))

    result = runner.invoke(auth_cmd.app, ["logout"])

    assert result.exit_code == 0
    assert deleted == ["work"]
    assert "Credentials removed for profile 'work'." in result.output


def test_auth_logout_all_profiles(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvs"
    _write_profiles_config(config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_dir / "config.toml")
    deleted: list[str] = []
    monkeypatch.setattr(auth_cmd.auth_mod, "delete_token", lambda profile: deleted.append(profile))

    result = runner.invoke(auth_cmd.app, ["logout", "--all"])

    assert result.exit_code == 0
    assert deleted == ["default", "work"]
    assert "Credentials removed for all profiles." in result.output


def test_auth_delete_profile_removes_config_and_token(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvs"
    _write_profiles_config(config_dir, default_profile="work")
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_dir / "config.toml")
    deleted: list[str] = []
    monkeypatch.setattr(auth_cmd.auth_mod, "delete_token", lambda profile: deleted.append(profile))

    result = runner.invoke(auth_cmd.profile_app, ["delete"])
    cfg = cfg_mod.load()

    assert result.exit_code == 0
    assert deleted == ["work"]
    assert "work" not in cfg.profiles
    assert cfg.default_profile == "default"
    assert "Profile 'work' deleted." in result.output


def test_auth_delete_all_profiles(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvs"
    _write_profiles_config(config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_dir / "config.toml")
    deleted: list[str] = []
    monkeypatch.setattr(auth_cmd.auth_mod, "delete_token", lambda profile: deleted.append(profile))

    result = runner.invoke(auth_cmd.profile_app, ["delete", "-a"])
    cfg = cfg_mod.load()

    assert result.exit_code == 0
    assert deleted == ["default", "work"]
    assert cfg.profiles == {}
    assert cfg.default_profile == "default"
    assert "All profiles deleted." in result.output


@dataclass
class _FakeResponse:
    status_code: int
    payload: dict[str, Any]

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict[str, Any]:
        return self.payload

    def raise_for_status(self) -> None:
        if not self.is_success:
            raise AssertionError(f"unexpected HTTP failure: {self.payload}")


class _FakeClient:
    responses: ClassVar[list[_FakeResponse]] = []
    requests: ClassVar[list[tuple[str, dict[str, Any] | None, dict[str, str] | None]]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> _FakeResponse:
        self.requests.append((url, json, headers))
        return self.responses.pop(0)


def test_device_login_handles_slow_down_and_stores_expiring_jwt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".rvs"
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_dir / "config.toml")
    _FakeClient.requests = []
    _FakeClient.responses = [
        _FakeResponse(
            200,
            {
                "device_code": "device-code",
                "user_code": "ABCD-1234",
                "verification_uri": "https://api.ravenstash.com/login/device",
                "verification_uri_complete": "https://api.ravenstash.com/login/device",
                "expires_in": 600,
                "interval": 5,
            },
        ),
        _FakeResponse(400, {"error": "authorization_pending"}),
        _FakeResponse(400, {"error": "slow_down"}),
        _FakeResponse(
            200,
            {
                "access_token": "jwt-token",
                "refresh_token": "refresh-token",
                "token_type": "Bearer",
                "expires_in": 900,
                "refresh_expires_in": 14400,
                "account_ref": "ac_23456789",
                "native_registries": NATIVE_REGISTRIES,
            },
        ),
    ]
    stored_tokens: list[tuple[str, str]] = []
    stored_refresh_tokens: list[tuple[str, str]] = []
    metadata_writes: list[dict[str, Any]] = []
    sleeps: list[int] = []

    monkeypatch.setattr(login_mod.httpx, "Client", _FakeClient)
    monkeypatch.setattr(
        login_mod.auth_mod,
        "set_token",
        lambda profile, token: stored_tokens.append((profile, token)),
    )
    monkeypatch.setattr(
        login_mod.auth_mod,
        "set_refresh_token",
        lambda profile, token: stored_refresh_tokens.append((profile, token)),
    )
    monkeypatch.setattr(
        login_mod.cfg_mod,
        "set_profile_metadata",
        lambda profile, **kwargs: metadata_writes.append({"profile": profile, **kwargs}),
    )
    monkeypatch.setattr(login_mod.auth_mod, "has_active_expiring_session", lambda profile: False)
    monkeypatch.setattr(login_mod, "_rvs_version", lambda: "0.1.0")
    monkeypatch.setattr(login_mod, "_device_platform", lambda: "linux")
    monkeypatch.setattr(login_mod.time, "sleep", lambda seconds: sleeps.append(seconds))

    login_mod.perform_device_login(
        profile="default",
        api_url="https://api.ravenstash.com",
        no_browser=False,
        duration="12h",
    )

    assert stored_tokens == [("default", "jwt-token")]
    assert stored_refresh_tokens == [("default", "refresh-token")]
    assert len(metadata_writes) == 1
    assert metadata_writes[0]["profile"] == "default"
    assert metadata_writes[0]["api_url"] == "https://api.ravenstash.com"
    assert metadata_writes[0]["customer_id"] == "ac_23456789"
    assert metadata_writes[0]["customer_unique_id"] is None
    assert metadata_writes[0]["native_registries"] == NATIVE_REGISTRIES
    assert metadata_writes[0]["credential_type"] == "expiring"
    assert metadata_writes[0]["expires_at"]
    assert metadata_writes[0]["refresh_expires_at"]
    assert sleeps == [5, 10]
    assert [url for url, _payload, _headers in _FakeClient.requests] == [
        "https://api.ravenstash.com/v0/auth/device/code",
        "https://api.ravenstash.com/v0/auth/device/token",
        "https://api.ravenstash.com/v0/auth/device/token",
        "https://api.ravenstash.com/v0/auth/device/token",
    ]
    first_payload = _FakeClient.requests[0][1]
    assert first_payload is not None
    assert first_payload["platform"] == "linux"
    assert first_payload["requested_duration_seconds"] == 12 * 60 * 60
    assert [headers for _url, _payload, headers in _FakeClient.requests] == [
        {"User-Agent": "rvs/0.1.0"},
        {"User-Agent": "rvs/0.1.0"},
        {"User-Agent": "rvs/0.1.0"},
        {"User-Agent": "rvs/0.1.0"},
    ]


def test_device_login_replaces_active_profile_and_revokes_previous_refresh(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".rvs"
    _write_profiles_config(config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_dir / "config.toml")
    monkeypatch.setenv("RVS_API_URL", "https://api.redirect.example.test")
    monkeypatch.setattr(login_mod.auth_mod, "has_active_expiring_session", lambda profile: True)
    monkeypatch.setattr(login_mod.auth_mod, "get_refresh_token", lambda profile: "old-refresh")
    _FakeClient.requests = []
    _FakeClient.responses = [
        _FakeResponse(
            200,
            {
                "device_code": "device-code",
                "user_code": "ABCD-1234",
                "verification_uri": "https://api.ravenstash.com/login/device",
                "verification_uri_complete": "https://api.ravenstash.com/login/device",
                "expires_in": 600,
                "interval": 5,
            },
        ),
        _FakeResponse(
            200,
            {
                "access_token": "jwt-token",
                "refresh_token": "new-refresh-token",
                "token_type": "Bearer",
                "expires_in": 900,
                "refresh_expires_in": 14400,
                "account_ref": "ac_23456789",
                "native_registries": NATIVE_REGISTRIES,
            },
        ),
    ]
    stored_tokens: list[tuple[str, str]] = []
    stored_refresh_tokens: list[tuple[str, str]] = []
    revoked: list[tuple[str, str]] = []
    info_messages: list[str] = []

    monkeypatch.setattr(login_mod.httpx, "Client", _FakeClient)
    monkeypatch.setattr(
        login_mod.auth_mod,
        "set_token",
        lambda profile, token: stored_tokens.append((profile, token)),
    )
    monkeypatch.setattr(
        login_mod.auth_mod,
        "set_refresh_token",
        lambda profile, token: stored_refresh_tokens.append((profile, token)),
    )
    monkeypatch.setattr(
        login_mod.auth_mod,
        "revoke_device_refresh_token",
        lambda api_url, token: revoked.append((api_url, token)) or True,
    )
    monkeypatch.setattr(login_mod.output, "info", lambda message: info_messages.append(message))
    monkeypatch.setattr(login_mod, "_rvs_version", lambda: "0.1.0")
    monkeypatch.setattr(login_mod, "_device_platform", lambda: "linux")

    login_mod.perform_device_login(
        profile="default",
        api_url=None,
        no_browser=True,
    )

    assert stored_tokens == [("default", "jwt-token")]
    assert stored_refresh_tokens == [("default", "new-refresh-token")]
    assert revoked == [("https://api.ravenstash.com", "old-refresh")]
    assert any("already authenticated" in message for message in info_messages)
    profile = cfg_mod.load().profiles["default"]
    assert profile.api_url == "https://api.redirect.example.test"
    assert profile.refresh_expires_at is not None


def test_device_login_start_failure_does_not_replace_stored_api_origin(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".rvs"
    _write_profiles_config(config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_dir / "config.toml")
    monkeypatch.setenv("RVS_API_URL", "https://api.redirect.example.test")
    monkeypatch.setattr(login_mod.auth_mod, "has_active_expiring_session", lambda profile: False)
    _FakeClient.requests = []
    _FakeClient.responses = [_FakeResponse(503, {"error": "unavailable"})]
    monkeypatch.setattr(login_mod.httpx, "Client", _FakeClient)

    with pytest.raises(SystemExit):
        login_mod.perform_device_login(
            profile="default",
            api_url=None,
            no_browser=True,
        )

    assert cfg_mod.stored_profile_api_url("default") == "https://api.ravenstash.com"


def test_device_login_does_not_revoke_expired_previous_refresh(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".rvs"
    _write_profiles_config(
        config_dir,
        refresh_expires_at="2000-01-01T00:00:00+00:00",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_dir / "config.toml")
    monkeypatch.setattr(login_mod.auth_mod, "has_active_expiring_session", lambda profile: False)
    _FakeClient.requests = []
    _FakeClient.responses = [
        _FakeResponse(
            200,
            {
                "device_code": "device-code",
                "user_code": "ABCD-1234",
                "verification_uri": "https://api.ravenstash.com/login/device",
                "verification_uri_complete": "https://api.ravenstash.com/login/device",
                "expires_in": 600,
                "interval": 5,
            },
        ),
        _FakeResponse(
            200,
            {
                "access_token": "jwt-token",
                "refresh_token": "new-refresh-token",
                "token_type": "Bearer",
                "expires_in": 900,
                "refresh_expires_in": 14400,
                "account_ref": "ac_23456789",
                "native_registries": NATIVE_REGISTRIES,
            },
        ),
    ]
    revoked: list[tuple[str, str]] = []
    info_messages: list[str] = []

    monkeypatch.setattr(login_mod.httpx, "Client", _FakeClient)
    monkeypatch.setattr(login_mod.auth_mod, "set_token", lambda _profile, _token: None)
    monkeypatch.setattr(
        login_mod.auth_mod,
        "set_refresh_token",
        lambda _profile, _token: None,
    )
    monkeypatch.setattr(
        login_mod.auth_mod,
        "revoke_device_refresh_token",
        lambda api_url, token: revoked.append((api_url, token)) or True,
    )
    monkeypatch.setattr(login_mod.output, "info", lambda message: info_messages.append(message))
    monkeypatch.setattr(login_mod, "_rvs_version", lambda: "0.1.0")
    monkeypatch.setattr(login_mod, "_device_platform", lambda: "linux")

    login_mod.perform_device_login(
        profile="default",
        api_url=None,
        no_browser=True,
    )

    assert revoked == []
    assert not any("already authenticated" in message for message in info_messages)


@pytest.mark.parametrize("error", [OSError("disk full"), ValueError("invalid schema")])
def test_store_expiring_credential_rolls_back_when_metadata_cannot_be_saved(
    monkeypatch, error: Exception
) -> None:
    deleted: list[tuple[str, str]] = []
    monkeypatch.setattr(login_mod.auth_mod, "set_token", lambda *_args: None)
    monkeypatch.setattr(login_mod.auth_mod, "set_refresh_token", lambda *_args: None)
    monkeypatch.setattr(
        login_mod.auth_mod,
        "delete_token_from_store",
        lambda profile, store: deleted.append((profile, store)),
    )
    monkeypatch.setattr(
        login_mod.cfg_mod,
        "set_profile_metadata",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(RuntimeError, match=str(error)):
        login_mod._store_expiring_credential(
            profile="default",
            api_url="https://api.ravenstash.com",
            token="access",
            refresh_token="refresh",
            customer_id="cus_123",
            customer_unique_id="custpid1",
            native_registries=NATIVE_REGISTRIES,
            expires_in=900,
            refresh_expires_in=14400,
            credential_store="pass",
        )

    assert deleted == [("default", "pass")]


@pytest.mark.parametrize("credential_type", ["expiring", "temporary"])
def test_refresh_expiring_credential_rotates_tokens(
    monkeypatch,
    tmp_path: Path,
    credential_type: str,
) -> None:
    config_dir = tmp_path / ".rvs"
    _write_profiles_config(config_dir, credential_type=credential_type)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_dir / "config.toml")
    monkeypatch.setenv("RVS_REPOSITORY_DOMAIN", "packages.enterprise.example")
    monkeypatch.setattr(auth_mod, "_keyring_available", lambda: True)
    monkeypatch.setattr(
        auth_mod,
        "_kr_get",
        lambda profile: "old-refresh" if profile == "default:refresh" else None,
    )
    stored: list[tuple[str, str]] = []
    _FakeClient.requests = []
    _FakeClient.responses = [
        _FakeResponse(
            200,
            {
                "access_token": "new-jwt",
                "refresh_token": "new-refresh",
                "token_type": "Bearer",
                "expires_in": 900,
                "refresh_expires_in": 14400,
                "account_ref": "ac_23456789",
                "native_registries": NATIVE_REGISTRIES,
            },
        )
    ]

    monkeypatch.setattr(auth_mod.httpx, "Client", _FakeClient)
    monkeypatch.setattr(auth_mod, "_rvs_user_agent", lambda: "rvs/0.1.0")
    monkeypatch.setattr(auth_mod, "_device_platform", lambda: "linux")
    monkeypatch.setattr(auth_mod, "_kr_set", lambda profile, token: stored.append((profile, token)))

    assert auth_mod.refresh_expiring_credential("default") == "new-jwt"
    assert stored == [
        ("default:refresh", "new-refresh"),
        ("default", "new-jwt"),
    ]
    assert _FakeClient.requests == [
        (
            "https://api.ravenstash.com/v0/auth/device/refresh",
            {"refresh_token": "old-refresh", "platform": "linux", "operation_id": ANY},
            {"User-Agent": "rvs/0.1.0"},
        )
    ]
    profile = cfg_mod.load().profiles["default"]
    assert profile.credential_type == "expiring"
    assert profile.customer_unique_id is None
    assert (
        profile.native_registries.pypi.read_base_url == "https://pypi.packages.enterprise.example"
    )
    assert (
        profile.native_registries.pypi.push_base_url
        == "https://push.pypi.packages.enterprise.example"
    )
    assert (
        profile.native_registries.oci_registry_base_url == "https://oci.packages.enterprise.example"
    )
    assert profile.refresh_expires_at is not None


def test_revoke_device_refresh_token_posts_to_devapi(monkeypatch) -> None:
    _FakeClient.requests = []
    _FakeClient.responses = [_FakeResponse(204, {})]

    monkeypatch.setattr(auth_mod.httpx, "Client", _FakeClient)
    monkeypatch.setattr(auth_mod, "_rvs_user_agent", lambda: "rvs/0.1.0")

    assert auth_mod.revoke_device_refresh_token(
        "https://api.ravenstash.com",
        "old-refresh",
    )
    assert _FakeClient.requests == [
        (
            "https://api.ravenstash.com/v0/auth/device/revoke",
            {"refresh_token": "old-refresh"},
            {"User-Agent": "rvs/0.1.0"},
        )
    ]


def test_refresh_storage_failure_revokes_and_removes_partial_pair(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".rvs"
    _write_profiles_config(config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_dir / "config.toml")
    monkeypatch.setattr(auth_mod, "_keyring_available", lambda: True)
    monkeypatch.setattr(
        auth_mod,
        "_kr_get",
        lambda profile: "old-refresh" if profile == "default:refresh" else None,
    )
    _FakeClient.requests = []
    _FakeClient.responses = [
        _FakeResponse(
            200,
            {
                "access_token": "new-jwt",
                "refresh_token": "new-refresh",
                "expires_in": 900,
                "refresh_expires_in": 14400,
            },
        )
    ]
    writes: list[str] = []
    deleted: list[tuple[str, str]] = []
    revoked: list[tuple[str, str]] = []

    def fail_second_write(profile: str, _token: str) -> None:
        writes.append(profile)
        if profile == "default":
            raise RuntimeError("locked during write")

    monkeypatch.setattr(auth_mod.httpx, "Client", _FakeClient)
    monkeypatch.setattr(
        auth_mod, "_store_set", lambda _store, profile, token: fail_second_write(profile, token)
    )
    monkeypatch.setattr(
        auth_mod,
        "delete_token_from_store",
        lambda profile, store: deleted.append((profile, store)),
    )
    monkeypatch.setattr(
        auth_mod,
        "revoke_device_refresh_token",
        lambda api_url, token: revoked.append((api_url, token)) or True,
    )

    assert auth_mod.refresh_expiring_credential("default") is None
    assert writes == ["default:refresh", "default"]
    assert deleted == [("default", "keyring")]
    assert revoked == [("https://api.ravenstash.com", "new-refresh")]
    assert cfg_mod.load().profiles["default"].credential_type is None


def test_refresh_expiring_credential_failure_clears_profile(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvs"
    _write_profiles_config(config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_dir / "config.toml")
    monkeypatch.setattr(auth_mod, "_keyring_available", lambda: True)
    monkeypatch.setattr(
        auth_mod,
        "_kr_get",
        lambda profile: "old-refresh" if profile == "default:refresh" else None,
    )
    deleted: list[str] = []
    _FakeClient.requests = []
    _FakeClient.responses = [
        _FakeResponse(401, {"detail": "Invalid refresh token"}),
    ]

    monkeypatch.setattr(auth_mod.httpx, "Client", _FakeClient)
    monkeypatch.setattr(auth_mod, "_rvs_user_agent", lambda: "rvs/0.1.0")
    monkeypatch.setattr(auth_mod, "_device_platform", lambda: "linux")
    monkeypatch.setattr(auth_mod, "delete_token", lambda profile: deleted.append(profile))

    assert auth_mod.refresh_expiring_credential("default") is None
    assert deleted == ["default"]
    assert _FakeClient.requests == [
        (
            "https://api.ravenstash.com/v0/auth/device/refresh",
            {"refresh_token": "old-refresh", "platform": "linux", "operation_id": ANY},
            {"User-Agent": "rvs/0.1.0"},
        )
    ]


def test_ambiguous_refresh_keeps_operation_across_invocations(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvs"
    _write_profiles_config(config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_dir / "config.toml")
    monkeypatch.setattr(auth_mod, "_keyring_available", lambda: True)
    monkeypatch.setattr(
        auth_mod, "_kr_get", lambda profile: "old-refresh" if profile.endswith(":refresh") else None
    )
    deleted: list[str] = []
    monkeypatch.setattr(auth_mod, "delete_token", deleted.append)
    _FakeClient.requests = []
    _FakeClient.responses = [
        _FakeResponse(502, {}),
        _FakeResponse(
            409, {"detail": {"code": "refresh_response_unavailable", "recovery": "sign_in"}}
        ),
    ]
    monkeypatch.setattr(auth_mod.httpx, "Client", _FakeClient)

    assert auth_mod.refresh_expiring_credential("default") is None
    pending = list(config_dir.glob("*.pending.json"))
    assert len(pending) == 1
    if os.name != "nt":
        assert pending[0].stat().st_mode & 0o777 == 0o600
    metadata = pending[0].read_text()
    assert "old-refresh" not in metadata
    operation_id = json.loads(metadata)["operation_id"]
    assert str(UUID(operation_id)) == operation_id
    assert deleted == []

    assert auth_mod.refresh_expiring_credential("default") is None
    assert deleted == ["default"]
    assert not list(config_dir.glob("*.pending.json"))
    assert [body["operation_id"] for _, body, _ in _FakeClient.requests if body] == [
        operation_id,
        operation_id,
    ]


def test_concurrent_refresh_reuses_rotated_pair(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvs"
    _write_profiles_config(config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_dir / "config.toml")
    monkeypatch.setattr(auth_mod, "_keyring_available", lambda: True)

    credentials = {
        "default": "old-access",
        "default:refresh": "old-refresh",
    }
    credentials_guard = threading.Lock()
    first_has_lock = threading.Event()
    second_read_old_refresh = threading.Event()
    original_refresh_lock = auth_mod._profile_refresh_lock

    def credential_get(account: str) -> str | None:
        with credentials_guard:
            value = credentials.get(account)
        if (
            threading.current_thread().name == "refresh-two"
            and account == "default:refresh"
            and value == "old-refresh"
        ):
            second_read_old_refresh.set()
        return value

    def credential_set(account: str, value: str) -> None:
        with credentials_guard:
            credentials[account] = value

    @contextmanager
    def tracked_refresh_lock(profile: str):
        with original_refresh_lock(profile):
            if threading.current_thread().name == "refresh-one":
                first_has_lock.set()
            yield

    http_calls: list[str] = []

    class CoordinatedClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            del args

        def post(self, _url, *, headers, json):
            del headers
            http_calls.append(json["refresh_token"])
            assert second_read_old_refresh.wait(timeout=5)
            return _FakeResponse(
                200,
                {
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_in": 900,
                    "refresh_expires_in": 14400,
                },
            )

    monkeypatch.setattr(auth_mod, "_kr_get", credential_get)
    monkeypatch.setattr(auth_mod, "_kr_set", credential_set)
    monkeypatch.setattr(auth_mod, "_profile_refresh_lock", tracked_refresh_lock)
    monkeypatch.setattr(auth_mod.httpx, "Client", CoordinatedClient)

    results: dict[str, str | None] = {}

    def refresh() -> None:
        results[threading.current_thread().name] = auth_mod.refresh_expiring_credential(
            "default", stale_access_token="old-access"
        )

    first = threading.Thread(target=refresh, name="refresh-one")
    second = threading.Thread(target=refresh, name="refresh-two")
    first.start()
    assert first_has_lock.wait(timeout=5)
    second.start()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert results == {"refresh-one": "new-access", "refresh-two": "new-access"}
    assert http_calls == ["old-refresh"]
