"""Commands for inspecting the effective user, profile, account, and target."""

from __future__ import annotations

import typer

from .. import config as cfg_mod
from .. import output
from ..account.commands import customers, display_name
from ..client import ApiClient, ApiError


app = typer.Typer(
    name="context",
    help="Inspect the effective user, local profile, acting account, and package target.",
    no_args_is_help=True,
)


def _account_display(profile_name: str) -> tuple[str, cfg_mod.AccountContext | None]:
    cfg = cfg_mod.load()
    customer_id = cfg_mod.current_customer_id(profile_name, cfg)
    cached = cfg_mod.cached_account(profile_name, customer_id)
    if cached is not None:
        return display_name(cached), cached

    profile = cfg.profiles.get(profile_name)
    if profile is not None and customer_id == profile.customer_id:
        return "personal", None

    items = customers(profile_name)
    if customer_id:
        matches = [item for item in items if item.get("customer_id") == customer_id]
    else:
        matches = [item for item in items if item.get("account_type") == "personal"]
    if len(matches) != 1 and customer_id:
        return f"unresolved:{customer_id}", None
    if len(matches) != 1:
        return "not selected", None
    selected = matches[0]
    if selected.get("account_type") == "personal":
        return "personal", None
    return f"org:{selected.get('account_label') or 'unknown'}", None


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
    """Verify and show the complete effective Ravenstash CLI context."""
    cfg = cfg_mod.load()
    profile_name = profile or cfg_mod.current_profile_name(cfg)
    selected_profile = cfg.active_profile(profile_name)
    try:
        identity = ApiClient.from_profile(profile_name).get("/v0/me").json()
    except ApiError as exc:
        output.fatal(f"Could not verify the effective Ravenstash context: {exc}")

    account_name, account = _account_display(profile_name)
    target = account.selected_target if account is not None else None
    output.kv(
        {
            "User": _identity_display(identity),
            "Local profile": profile_name,
            "Profile selection source": (
                "command option (--profile)" if profile else cfg_mod.profile_selection_source()
            ),
            "Acting account": account_name,
            "Account selection source": cfg_mod.account_selection_source(profile_name, cfg),
            "Package target": target.display_selector if target is not None else "not selected",
            "DevAPI URL": selected_profile.api_url,
        },
        title="Current Ravenstash CLI context",
    )
