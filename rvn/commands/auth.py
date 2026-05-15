"""rvn auth — multi-registry authentication management.

Wraps the core login/logout flow and adds commands to configure per-kind
registry overrides (separate URLs and tokens for PyPI, npm, and Maven).

    rvn auth login                        # interactive login (default profile)
    rvn auth login --profile work         # login to a named profile
    rvn auth logout                       # remove credentials
    rvn auth add-registry --kind pypi \\
        --api-url https://api.myhost.com \\
        --token rvn_tok_... \\
        --repo my-pypi                    # per-kind override
    rvn auth list                         # show all profiles + per-kind overrides
    rvn auth status                       # verify current token against the API
"""

from __future__ import annotations

import getpass

import httpx
import typer

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import output
from ..client import ApiClient, ApiError


app = typer.Typer(
    name="auth",
    help="Multi-registry authentication management — login, logout, per-kind overrides.",
    no_args_is_help=True,
)


# ── login ─────────────────────────────────────────────────────────────────────


@app.command("login")
def auth_login(
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

    \b
        rvn auth login
        rvn auth login --profile work --api-url https://api.mycompany.com
        rvn auth login --email me@example.com
    """
    cfg = cfg_mod.load()
    existing_profile = cfg.profiles.get(profile)
    resolved_api_url = api_url or (
        existing_profile.api_url if existing_profile else "https://api.ravenstash.com"
    )

    if api_url:
        cfg_mod.set_profile_value(profile, api_url=api_url)

    if not email:
        email = typer.prompt("Email")
    password = getpass.getpass("Password: ")

    output.info(f"Authenticating with {resolved_api_url} ...")
    try:
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


# ── logout ────────────────────────────────────────────────────────────────────


@app.command("logout")
def auth_logout(
    profile: str = typer.Option(
        "default", "--profile", "-p", help="Profile to remove credentials from."
    ),
) -> None:
    """Remove stored credentials for a profile.

    \b
        rvn auth logout
        rvn auth logout --profile work
    """
    auth_mod.delete_token(profile)
    output.success(f"Credentials removed for profile '{profile}'.")


# ── add-registry ──────────────────────────────────────────────────────────────


@app.command("add-registry")
def auth_add_registry(
    kind: str = typer.Option(
        ...,
        "--kind",
        "-k",
        help="Registry kind: pypi | npm | maven",
    ),
    api_url: str | None = typer.Option(
        None,
        "--api-url",
        help="API URL for this registry kind (overrides the active profile URL).",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        "-t",
        help="Auth token for this registry kind (overrides the active profile token).",
    ),
    repo: str | None = typer.Option(
        None,
        "--repo",
        "-r",
        help="Default repository slug for this registry kind.",
    ),
) -> None:
    """Configure per-kind registry credentials and defaults.

    Use this when you have separate API URLs or tokens for different
    registry kinds (e.g. PyPI on one host, npm on another), or when
    you want to pin a default repository slug per kind.

    \b
        # Point the pypi kind at a custom host + set a token
        rvn auth add-registry --kind pypi \\
            --api-url https://api.myhost.com \\
            --token rvn_tok_... \\
            --repo my-pypi

        # Just set the default repo for npm, reuse the profile token
        rvn auth add-registry --kind npm --repo my-npm

        # Override only the token for maven
        rvn auth add-registry --kind maven --token rvn_tok_mvn_...
    """
    allowed = {"pypi", "npm", "maven"}
    if kind not in allowed:
        output.fatal(f"Invalid kind '{kind}'. Must be one of: {', '.join(sorted(allowed))}")

    cfg_mod.set_registry_override(
        kind=kind,  # type: ignore[arg-type]
        api_url=api_url,
        token=token,
        default_repo=repo,
    )

    parts = []
    if api_url:
        parts.append(f"api-url={api_url}")
    if token:
        parts.append("token=***")
    if repo:
        parts.append(f"repo={repo}")

    changes = ", ".join(parts) or "(no changes)"
    output.success(f"Registry '{kind}' updated: {changes}")


# ── list ──────────────────────────────────────────────────────────────────────


@app.command("list")
def auth_list() -> None:
    """Show all configured profiles and per-kind registry overrides.

    \b
        rvn auth list
    """
    cfg = cfg_mod.load()

    output.section("Profiles")
    if not cfg.profiles:
        output.info("  (none configured — run `rvn auth login`)")
    else:
        rows: list[list[str]] = []
        for name, p in cfg.profiles.items():
            default_marker = " (active)" if name == cfg.default_profile else ""
            has_token = "yes" if auth_mod.get_token(name) or p.token else "no"
            rows.append([f"{name}{default_marker}", p.api_url, has_token])
        output.table(["Profile", "API URL", "Token stored"], rows)

    output.section("Per-kind registry overrides")
    if not cfg.registries:
        output.info("  (none — run `rvn auth add-registry`)")
    else:
        rows = []
        for kind, r in cfg.registries.items():
            rows.append(
                [
                    kind,
                    r.default_repo or "(not set)",
                    r.api_url or "(uses profile)",
                    "yes" if r.token else "(uses profile)",
                ]
            )
        output.table(["Kind", "Default repo", "API URL override", "Token override"], rows)


# ── status ────────────────────────────────────────────────────────────────────


@app.command("status")
def auth_status(
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Profile to check (default: active profile)."
    ),
) -> None:
    """Verify the stored token is valid against the API.

    \b
        rvn auth status
        rvn auth status --profile work
    """
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile) or p.token

    if not token:
        output.error("No credentials found. Run `rvn auth login`.")
        raise typer.Exit(1)

    client = ApiClient(api_url=p.api_url, token=token)
    try:
        client.get("/webapp/account/me")
        output.success(f"Authenticated as active user. API: {p.api_url}")
    except ApiError as exc:
        if exc.status_code == 401:
            output.error("Token is invalid or expired. Run `rvn auth login` to refresh.")
        else:
            output.error(f"API returned {exc.status_code}: {exc}")
        raise typer.Exit(1) from exc
