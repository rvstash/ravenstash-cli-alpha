from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

from rvs.auth import stores


if TYPE_CHECKING:
    from pathlib import Path


def test_pass_status_requires_initialized_store(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(stores.shutil, "which", lambda command: "/usr/bin/pass")
    monkeypatch.setattr(stores, "_password_store_dir", lambda: tmp_path)

    status = stores.pass_status()

    assert status.available is False
    assert "not initialized" in status.detail


def test_pass_status_accepts_initialized_store(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".gpg-id").write_text("developer@example.test\n", encoding="utf-8")
    monkeypatch.setattr(stores.shutil, "which", lambda command: "/usr/bin/pass")
    monkeypatch.setattr(stores, "_password_store_dir", lambda: tmp_path)

    status = stores.pass_status()

    assert status.available is True
    assert status.backend == "/usr/bin/pass"


def test_pass_set_sends_secret_only_over_stdin(monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(stores.subprocess, "run", fake_run)

    stores.pass_set("profile/with/slashes", "secret-token")

    command, kwargs = calls[0]
    assert command[:4] == ["pass", "insert", "--multiline", "--force"]
    assert "profile/with/slashes" not in command[-1]
    assert "secret-token" not in command
    assert kwargs["input"] == "secret-token"
