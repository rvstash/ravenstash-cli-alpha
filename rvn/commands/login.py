"""Shared device authorization implementation for rvn auth login."""

from __future__ import annotations

import importlib.metadata
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import typer
from rich.live import Live

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import output


app = typer.Typer(help="Authenticate with Ravenstash.")

_POLL_FRAMES = ("🔄", "🔃")


def _rvn_version() -> str:
    try:
        return importlib.metadata.version("rvn")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


def _resolve_api_url(profile: str, api_url: str | None) -> str:
    cfg = cfg_mod.load()
    existing_profile = cfg.profiles.get(profile)
    if api_url:
        return api_url.rstrip("/")
    if existing_profile:
        return existing_profile.api_url.rstrip("/")
    return cfg_mod.DEFAULT_API_URLS.get(profile, cfg_mod.DEFAULT_API_URLS["default"])


def _error_code(response: httpx.Response) -> str | None:
    try:
        payload: Any = response.json()
    except ValueError:
        return None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, str):
            return error
        detail = payload.get("detail")
        if isinstance(detail, dict):
            nested = detail.get("error")
            if isinstance(nested, str):
                return nested
    return None


def _store_temporary_credential(
    *,
    profile: str,
    api_url: str,
    token: str,
    customer_id: str | None,
    expires_in: int,
) -> None:
    try:
        auth_mod.set_token(profile, token)
    except RuntimeError as exc:
        output.fatal(str(exc))

    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    cfg_mod.set_profile_metadata(
        profile,
        api_url=api_url,
        customer_id=customer_id,
        credential_type="temporary",
        expires_at=expires_at.isoformat(),
    )


def _print_browser_prompt(*, no_browser: bool) -> None:
    if no_browser:
        return

    output.info("Open the link in your browser, or CTRL+CLICK it from your terminal.")


class _AuthorizationPollDisplay:
    def __init__(self) -> None:
        self._enabled = output.console.is_terminal
        self._live: Live | None = None
        self._frame = 0

    def __enter__(self) -> _AuthorizationPollDisplay:
        if self._enabled:
            self._live = Live(
                self._render(),
                console=output.console,
                refresh_per_second=10,
                transient=True,
            )
            self._live.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()

    def stop(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    def sleep(self, seconds: int, *, tick: Any | None = None) -> None:
        if not self._enabled:
            if tick is not None:
                tick()
            time.sleep(seconds)
            return

        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if tick is not None:
                tick()
            self._refresh()
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    def _refresh(self) -> None:
        if self._live is None:
            return
        self._frame += 1
        self._live.update(self._render())

    def _render(self) -> str:
        frame = _POLL_FRAMES[self._frame % len(_POLL_FRAMES)]
        return f"[cyan]{frame}[/] device authorization in progress via UI"


def perform_device_login(
    *,
    profile: str,
    api_url: str | None,
    no_browser: bool,
) -> None:
    resolved_api_url = _resolve_api_url(profile, api_url)
    cfg_mod.set_profile_metadata(profile, api_url=resolved_api_url)

    try:
        with httpx.Client(timeout=15.0) as client:
            create_resp = client.post(
                f"{resolved_api_url}/v0/auth/device/code",
                json={
                    "client_name": "rvn CLI",
                    "rvn_version": _rvn_version(),
                },
            )
            create_resp.raise_for_status()
            session = create_resp.json()
    except Exception as exc:
        output.fatal(f"Could not start device login: {exc}")

    user_code = session["user_code"]
    approval_url = session["verification_uri"]
    output.info(f"Device code: {user_code}")
    output.info(f"Open this URL and enter the code to approve the device: {approval_url}")
    _print_browser_prompt(no_browser=no_browser)

    device_code = session["device_code"]
    interval = max(int(session.get("interval") or 5), 1)
    deadline = time.monotonic() + max(int(session.get("expires_in") or 600), 1)

    try:
        with httpx.Client(timeout=15.0) as client, _AuthorizationPollDisplay() as poll_display:
            while time.monotonic() < deadline:
                poll_resp = client.post(
                    f"{resolved_api_url}/v0/auth/device/token",
                    json={"device_code": device_code},
                )
                if poll_resp.is_success:
                    payload = poll_resp.json()
                    _store_temporary_credential(
                        profile=profile,
                        api_url=resolved_api_url,
                        token=payload["access_token"],
                        customer_id=payload.get("customer_id"),
                        expires_in=int(payload.get("expires_in") or 0),
                    )
                    poll_display.stop()
                    output.success(
                        f"Authenticated profile '{profile}' with a temporary credential."
                    )
                    return

                error = _error_code(poll_resp)
                if error == "authorization_pending":
                    poll_display.sleep(interval)
                    continue
                if error == "slow_down":
                    interval += 5
                    poll_display.sleep(interval)
                    continue
                if error == "access_denied":
                    output.fatal("Login was denied.")
                if error == "expired_token":
                    output.fatal("Login session expired before approval.")

                poll_resp.raise_for_status()
    except KeyboardInterrupt:
        output.fatal("Login cancelled.")
    except Exception as exc:
        output.fatal(f"Login failed: {exc}")

    output.fatal("Login session expired before approval.")


@app.callback(invoke_without_command=True)
def login(
    ctx: typer.Context,
    profile: str = typer.Option(
        "default",
        "--profile",
        "-p",
        help="Config profile to write credentials into.",
    ),
    api_url: str | None = typer.Option(
        None,
        "--api-url",
        help="Override DevAPI base URL (saved to profile).",
    ),
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Suppress the browser-opening hint.",
    ),
) -> None:
    """Authenticate with device authorization and store the short-lived JWT."""
    if ctx.invoked_subcommand is not None:
        return
    perform_device_login(profile=profile, api_url=api_url, no_browser=no_browser)


@app.command("logout")
def logout(
    profile: str = typer.Option(
        "default",
        "--profile",
        "-p",
        help="Profile to remove credentials from.",
    ),
) -> None:
    """Remove stored credentials for a profile."""
    auth_mod.delete_token(profile)
    output.success(f"Credentials removed for profile '{profile}'.")
