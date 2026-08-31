"""Commands for selecting the customer charged and authorized for package work."""

from __future__ import annotations

import os

import typer

from .. import config as cfg_mod
from .. import output
from ..client import ApiClient, ApiError


app = typer.Typer(
    name="account",
    help="Select the acting personal or organization account.",
    no_args_is_help=True,
)


def _profile_name(profile: str | None) -> str:
    return profile or cfg_mod.current_profile_name()


def customers(profile: str | None = None) -> list[dict]:
    try:
        payload = ApiClient.from_profile(profile).get("/v0/customers").json()
    except ApiError as exc:
        output.fatal(str(exc))
    if not isinstance(payload, list):
        output.fatal("The Ravenstash acting-account response is invalid.")
    return [item for item in payload if isinstance(item, dict)]


def resolve_account(selector: str, profile: str | None = None) -> dict:
    items = customers(profile)
    value = selector.strip()
    if not value:
        output.fatal("Acting-account selector cannot be empty.")

    lowered = value.casefold()
    if lowered == "personal":
        matches = [item for item in items if item.get("account_type") == "personal"]
    else:
        label = value[4:] if lowered.startswith("org:") else value
        label_folded = label.casefold()
        matches = [
            item
            for item in items
            if value
            in {
                item.get("customer_id"),
                item.get("customer_unique_id"),
                item.get("customer_unique_ref"),
            }
            or (
                isinstance(item.get("account_label"), str)
                and item["account_label"].casefold() == label_folded
                and (not lowered.startswith("org:") or item.get("account_type") == "organization")
            )
        ]
    if not matches:
        output.fatal(
            f"Acting account '{selector}' was not found for this local profile."
        )
    if len(matches) > 1:
        refs = ", ".join(str(item.get("customer_unique_ref")) for item in matches)
        output.fatal(f"Acting-account selector '{selector}' is ambiguous. Use one of: {refs}")
    selected = matches[0]
    cfg_mod.cache_account(
        profile=_profile_name(profile),
        customer=selected,
        activate=False,
    )
    return selected


def ensure_active_account(
    profile: str | None = None,
    customer_id: str | None = None,
) -> tuple[str, cfg_mod.AccountContext]:
    profile_name = _profile_name(profile)
    effective_id = customer_id or cfg_mod.current_customer_id(profile_name)
    if effective_id:
        cached = cfg_mod.cached_account(profile_name, effective_id)
        if cached is not None:
            return profile_name, cached
        profile_config = cfg_mod.load().active_profile(profile_name)
        if effective_id == profile_config.customer_id:
            customer = {
                "customer_id": effective_id,
                "customer_unique_ref": profile_config.customer_unique_id or effective_id,
                "account_type": "personal",
                "account_label": "personal",
                "organization_role": "owner",
                "authority_revision": None,
            }
        elif customer_id is not None:
            customer = {
                "customer_id": effective_id,
                "customer_unique_ref": effective_id,
                "account_type": "organization",
                "account_label": effective_id,
                "organization_role": None,
                "authority_revision": None,
            }
        else:
            customer = resolve_account(effective_id, profile_name)
    else:
        items = customers(profile_name)
        personal = [item for item in items if item.get("account_type") == "personal"]
        if len(personal) != 1:
            output.fatal("No acting account is selected. Run `rvs account use`.")
        customer = personal[0]
    return profile_name, cfg_mod.cache_account(
        profile=profile_name,
        customer=customer,
        activate=customer_id is None,
    )


def display_name(account: cfg_mod.AccountContext) -> str:
    if account.account_type == "personal":
        return "personal"
    return f"org:{account.account_label}"


@app.command("list")
def account_list(
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """List acting accounts available to one local profile."""
    profile_name = _profile_name(profile)
    active_id = cfg_mod.current_customer_id(profile_name)
    rows = []
    for item in customers(profile_name):
        customer_id = str(item.get("customer_id", ""))
        account_type = str(item.get("account_type", ""))
        label = "personal" if account_type == "personal" else f"org:{item.get('account_label')}"
        rows.append(
            [
                f"{label} (active)" if customer_id == active_id else label,
                str(item.get("customer_unique_ref", "")),
                str(item.get("organization_role", "")),
            ]
        )
    output.table(["Acting account", "Stable reference", "Role"], rows)


@app.command("current")
def account_current(
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show the acting account used for authorization and metering."""
    profile_name, account = ensure_active_account(profile)
    output.kv(
        {
            "Local profile": profile_name,
            "Acting account": display_name(account),
            "Selection source": cfg_mod.account_selection_source(profile_name),
            "Account label": account.account_label,
            "Stable reference": account.customer_unique_ref,
            "Role": account.organization_role or "unknown",
        },
        title="Current acting Ravenstash account",
    )


def _use_account(account: str, profile: str | None) -> None:
    profile_name = _profile_name(profile)
    selected = resolve_account(account, profile_name)
    scope = cfg_mod.account_selection_write_scope()
    saved = cfg_mod.set_active_account(profile=profile_name, customer=selected)
    output.success(f"Acting account '{display_name(saved)}' selected for {scope}.")
    if os.environ.get("RVS_CUSTOMER_ID"):
        output.warn(
            "RVS_CUSTOMER_ID is set and still overrides the acting account in this shell."
        )


@app.command("use")
def account_use(
    account: str = typer.Argument(
        ..., help="personal, org:<label>, or a stable account reference."
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Use an acting account in this shell or in the selected local profile."""
    _use_account(account, profile)
