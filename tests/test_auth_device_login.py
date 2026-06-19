from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from typer.testing import CliRunner


if TYPE_CHECKING:
    from pathlib import Path

from rvn import auth as auth_mod
from rvn import config as cfg_mod
from rvn.commands import auth as auth_cmd
from rvn.commands import login as login_mod


runner = CliRunner()


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


def _write_profiles_config(config_dir: Path, default_profile: str = "default") -> None:
    config_file = config_dir / "config.toml"
    config_dir.mkdir()
    config_file.write_text(
        f"""
default_profile = "{default_profile}"

[profiles.default]
api_url = "https://api.ravenstash.com"
customer_id = "cus_default"
credential_type = "temporary"
expires_at = "2099-01-01T00:00:00+00:00"

[profiles.work]
api_url = "https://api.work.example"
customer_id = "cus_work"
credential_type = "temporary"
expires_at = "2099-01-01T00:00:00+00:00"
""".strip(),
        encoding="utf-8",
    )


def test_rvn_token_takes_precedence_over_keyring(monkeypatch) -> None:
    monkeypatch.setenv("RVN_TOKEN", "env-token")
    monkeypatch.setattr(auth_mod, "_keyring_available", lambda: True)
    monkeypatch.setattr(auth_mod, "_kr_get", lambda profile: "keyring-token")

    assert auth_mod.get_token("default") == "env-token"
    assert auth_mod.token_source("default") == "RVN_TOKEN"


def test_config_token_is_ignored(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvn"
    config_file = config_dir / "config.toml"
    config_dir.mkdir()
    config_file.write_text(
        """
default_profile = "default"

[profiles.default]
api_url = "https://api.ravenstash.com"
token = "rvn_tok_old"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)
    monkeypatch.delenv("RVN_TOKEN", raising=False)
    monkeypatch.setattr(auth_mod, "_keyring_available", lambda: False)

    assert auth_mod.get_token("default") is None
    assert auth_mod.token_source("default") is None


def test_auth_switch_profile_sets_active_profile(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvn"
    _write_profiles_config(config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_dir / "config.toml")

    result = runner.invoke(auth_cmd.app, ["switch", "--profile", "work"])

    assert result.exit_code == 0
    assert cfg_mod.load().default_profile == "work"
    assert "Active profile set to 'work'." in result.output


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
    config_dir = tmp_path / ".rvn"
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
    config_dir = tmp_path / ".rvn"
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
    config_dir = tmp_path / ".rvn"
    _write_profiles_config(config_dir, default_profile="work")
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_dir / "config.toml")
    deleted: list[str] = []
    monkeypatch.setattr(auth_cmd.auth_mod, "delete_token", lambda profile: deleted.append(profile))

    result = runner.invoke(auth_cmd.app, ["delete"])
    cfg = cfg_mod.load()

    assert result.exit_code == 0
    assert deleted == ["work"]
    assert "work" not in cfg.profiles
    assert cfg.default_profile == "default"
    assert "Profile 'work' deleted." in result.output


def test_auth_delete_all_profiles(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvn"
    _write_profiles_config(config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_dir / "config.toml")
    deleted: list[str] = []
    monkeypatch.setattr(auth_cmd.auth_mod, "delete_token", lambda profile: deleted.append(profile))

    result = runner.invoke(auth_cmd.app, ["delete", "-a"])
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
    requests: ClassVar[list[tuple[str, dict[str, Any] | None]]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def post(self, url: str, json: dict[str, Any] | None = None) -> _FakeResponse:
        self.requests.append((url, json))
        return self.responses.pop(0)


def test_device_login_handles_slow_down_and_stores_temporary_jwt(monkeypatch) -> None:
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
                "token_type": "Bearer",
                "expires_in": 14400,
                "customer_id": "cus_123",
            },
        ),
    ]
    stored_tokens: list[tuple[str, str]] = []
    metadata_writes: list[dict[str, Any]] = []
    sleeps: list[int] = []

    monkeypatch.setattr(login_mod.httpx, "Client", _FakeClient)
    monkeypatch.setattr(
        login_mod.auth_mod,
        "set_token",
        lambda profile, token: stored_tokens.append((profile, token)),
    )
    monkeypatch.setattr(
        login_mod.cfg_mod,
        "set_profile_metadata",
        lambda profile, **kwargs: metadata_writes.append({"profile": profile, **kwargs}),
    )
    monkeypatch.setattr(login_mod.time, "sleep", lambda seconds: sleeps.append(seconds))

    login_mod.perform_device_login(
        profile="default", api_url="https://api.ravenstash.com", no_browser=False
    )

    assert stored_tokens == [("default", "jwt-token")]
    assert metadata_writes[0] == {
        "profile": "default",
        "api_url": "https://api.ravenstash.com",
    }
    assert metadata_writes[-1]["profile"] == "default"
    assert metadata_writes[-1]["api_url"] == "https://api.ravenstash.com"
    assert metadata_writes[-1]["customer_id"] == "cus_123"
    assert metadata_writes[-1]["credential_type"] == "temporary"
    assert metadata_writes[-1]["expires_at"]
    assert sleeps == [5, 10]
    assert [url for url, _payload in _FakeClient.requests] == [
        "https://api.ravenstash.com/v0/auth/device/code",
        "https://api.ravenstash.com/v0/auth/device/token",
        "https://api.ravenstash.com/v0/auth/device/token",
        "https://api.ravenstash.com/v0/auth/device/token",
    ]
