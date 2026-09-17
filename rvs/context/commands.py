"""Commands for inspecting the effective user, profile, account, and target."""

from __future__ import annotations

import typer

from .. import config as cfg_mod
from .. import output
from ..account.commands import accounts, display_name, payload_display_name
from ..client import ApiClient, ApiError


app = typer.Typer(
    name="context",
    help="Show who is signed in and which account and repository are selected.",
    no_args_is_help=True,
)


def _account_display(profile_name: str) -> tuple[str, cfg_mod.AccountContext | None]:
    cfg = cfg_mod.load()
    customer_id = cfg_mod.current_customer_id(profile_name, cfg)
    cached = cfg_mod.cached_account(profile_name, customer_id)
    if cached is not None:
        return display_name(cached), cached

    items = accounts(profile_name)
    if customer_id:
        matches = [item for item in items if item.get("account_ref") == customer_id]
    else:
        matches = [item for item in items if item.get("account_type") == "personal"]
    if len(matches) != 1 and customer_id:
        return f"unresolved:{customer_id}", None
    if len(matches) != 1:
        return "not selected", None
    return payload_display_name(matches[0]), None


def _identity_display(identity: object) -> str:
    if not isinstance(identity, dict):
        return "unknown"
    return str(identity.get("email") or identity.get("id") or "unknown")


@app.command("current")
def context_current(
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help="Local profile to inspect (default: selected profile).",
    ),
) -> None:
    """Show the current Ravenstash sign-in and selections."""
    cfg = cfg_mod.load()
    profile_name = profile or cfg_mod.current_profile_name(cfg)
    selected_profile = cfg.active_profile(profile_name)
    try:
        identity = ApiClient.from_profile(profile_name).get("/me").json()
    except ApiError as exc:
        output.fatal(f"Could not verify the current Ravenstash sign-in: {exc}")

    account_name, account = _account_display(profile_name)
    target = account.selected_target if account is not None else None
    output.kv(
        {
            "User": _identity_display(identity),
            "Local profile": profile_name,
            "Profile selected by": (
                "command option (--profile)" if profile else cfg_mod.profile_selection_source()
            ),
            "Account": account_name,
            "Account selected by": cfg_mod.account_selection_source(profile_name, cfg),
            "Repository or mirror": target.display_selector
            if target is not None
            else "not selected",
            "Ravenstash API": selected_profile.api_url,
        },
        title="Current Ravenstash CLI selections",
    )
