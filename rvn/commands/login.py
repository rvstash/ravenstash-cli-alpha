"""rvn login — authenticate against the Central API and persist credentials."""

from __future__ import annotations

import getpass

import typer

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import output


app = typer.Typer(help="Authenticate with a RavenStash instance.")


@app.callback(invoke_without_command=True)
def login(
    ctx: typer.Context,
    profile: str = typer.Option(
        "default", "--profile", "-p", help="Config profile to write credentials into."
    ),
    api_url: str | None = typer.Option(
        None, "--api-url", help="Override API base URL (saved to profile)."
    ),
    email: str | None = typer.Option(
        None, "--email", "-e", help="Account email (prompted if omitted)."
    ),
) -> None:
    """Authenticate and store credentials for a RavenStash instance.

    Prompts for email and password interactively when not provided via flags.
    The access token is stored in the system keyring (or config file as fallback).
    """
    if ctx.invoked_subcommand is not None:
        return

    cfg = cfg_mod.load()

    # Resolve API URL
    existing_profile = cfg.profiles.get(profile)
    resolved_api_url = api_url or (
        existing_profile.api_url if existing_profile else "https://api.ravenstash.com"
    )

    if api_url:
        cfg_mod.set_profile_value(profile, api_url=api_url)

    # Prompt credentials
    if not email:
        email = typer.prompt("Email")
    password = getpass.getpass("Password: ")

    output.info(f"Authenticating with {resolved_api_url} ...")

    try:
        # hit login endpoint directly (bypasses token check)
        import httpx

        resp = httpx.post(
            f"{resolved_api_url.rstrip('/')}/webapp/auth/login",
            json={"email": email, "password": password},
            timeout=15.0,
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]
    except Exception as exc:
        output.fatal(f"Login failed: {exc}")

    auth_mod.set_token(profile, token)
    cfg_mod.set_profile_value(profile, api_url=resolved_api_url)

    output.success(f"Authenticated. Token saved for profile '{profile}'.")


@app.command("logout")
def logout(
    profile: str = typer.Option(
        "default", "--profile", "-p", help="Profile to remove credentials from."
    ),
) -> None:
    """Remove stored credentials for a profile."""
    auth_mod.delete_token(profile)
    output.success(f"Credentials removed for profile '{profile}'.")
