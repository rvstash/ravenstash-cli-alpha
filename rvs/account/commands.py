"""Commands for choosing a personal account or organization."""

from __future__ import annotations

import os

import typer
from rich.markup import escape

from .. import config as cfg_mod
from .. import output
from ..client import ApiClient, ApiError
from ..interactive import select_index


app = typer.Typer(
    name="account",
    help="Choose the personal account or organization to use.",
    no_args_is_help=True,
)


def _profile_name(profile: str | None) -> str:
    return profile or cfg_mod.current_profile_name()


def accounts(profile: str | None = None) -> list[dict]:
    try:
        payload = ApiClient.from_profile(profile).get("/accounts").json()
        if isinstance(payload, dict):
            payload = payload.get("items", [])
    except ApiError as exc:
        output.fatal(str(exc))
    if not isinstance(payload, list):
        output.fatal("Ravenstash returned an invalid account list.")
    return [item for item in payload if isinstance(item, dict)]


def _public_handle(account: dict) -> str:
    handle = account.get("account_handle")
    if not isinstance(handle, str) or not handle.strip():
        output.fatal("Ravenstash returned an account without a public handle.")
    return handle.strip()


def resolve_account(selector: str, profile: str | None = None) -> dict:
    items = accounts(profile)
    value = selector.strip()
    if not value:
        output.fatal("Account name cannot be empty.")

    lowered = value.casefold()
    handle_selector = value[4:] if lowered.startswith("org:") else value
    handle_selector_folded = handle_selector.casefold()
    handle_matches = [
        item
        for item in items
        if isinstance(item.get("account_handle"), str)
        and item["account_handle"].casefold() == handle_selector_folded
        and (not lowered.startswith("org:") or item.get("account_type") == "organization")
    ]
    if handle_matches:
        matches = handle_matches
    elif lowered == "personal":
        matches = [item for item in items if item.get("account_type") == "personal"]
    else:
        matches = [item for item in items if value == item.get("account_ref")]
    if not matches:
        output.fatal(f"Account '{selector}' was not found for this profile.")
    if len(matches) > 1:
        refs = ", ".join(str(item.get("account_ref")) for item in matches)
        output.fatal(
            f"More than one account matches '{selector}'. "
            f"Use one of these account references: {refs}"
        )
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
                "account_ref": effective_id,
                "account_type": "personal",
                "account_label": "personal",
                "organization_role": "owner",
                "authority_revision": None,
            }
        elif customer_id is not None:
            customer = {
                "account_ref": effective_id,
                "account_type": "organization",
                "account_label": effective_id,
                "organization_role": None,
                "authority_revision": None,
            }
        else:
            customer = resolve_account(effective_id, profile_name)
    else:
        items = accounts(profile_name)
        personal = [item for item in items if item.get("account_type") == "personal"]
        if len(personal) != 1:
            output.fatal("No account is selected. Run `rvs account switch`.")
        customer = personal[0]
    return profile_name, cfg_mod.cache_account(
        profile=profile_name,
        customer=customer,
        activate=customer_id is None,
    )


def display_name(account: cfg_mod.AccountContext) -> str:
    if account.customer_handle:
        return account.customer_handle
    if account.account_type == "personal":
        return "personal"
    return f"org:{account.account_label}"


@app.command("list")
def account_list(
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """List personal accounts and organizations available to one profile."""
    profile_name = _profile_name(profile)
    active_id = cfg_mod.current_customer_id(profile_name)
    rows = []
    for item in accounts(profile_name):
        account_ref = str(item.get("account_ref", ""))
        label = _public_handle(item)
        rows.append(
            [
                f"{label} (active)" if account_ref == active_id else label,
                account_ref,
                str(item.get("organization_role", "")),
            ]
        )
    output.table(["Account", "Account ref", "Role"], rows)


@app.command("current")
def account_current(
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show the selected personal account or organization."""
    profile_name, account = ensure_active_account(profile)
    output.kv(
        {
            "Local profile": profile_name,
            "Account": display_name(account),
            "Selected by": cfg_mod.account_selection_source(profile_name),
            "Display name": account.account_label,
            "Username or handle": account.customer_handle or "unknown",
            "Account ref": account.customer_unique_ref,
            "Role": account.organization_role or "unknown",
        },
        title="Current Ravenstash account",
    )


def _render_account_selector(
    items: list[dict],
    selected_index: int,
    active_account_ref: str | None,
) -> str:
    lines = [
        "[bold]Select Ravenstash account[/]",
        "[dim]Use up/down and ENTER to confirm.[/]",
        "",
    ]
    for index, item in enumerate(items):
        handle = escape(_public_handle(item))
        account_ref = str(item.get("account_ref", ""))
        account_type = item.get("account_type")
        role = str(item.get("organization_role") or "")
        kind = "Personal" if account_type == "personal" else "Organization"
        detail = f"{kind} · {role}" if role else kind
        active = " [dim](active)[/]" if account_ref == active_account_ref else ""
        pointer = ">" if index == selected_index else " "
        label = f"[bold]{handle}[/]" if index == selected_index else handle
        lines.append(f"[cyan]{pointer}[/] {label} [dim]{escape(detail)}[/]{active}")
    return "\n".join(lines)


def _select_account_interactive(profile_name: str) -> dict:
    items = accounts(profile_name)
    if not items:
        output.fatal("No accounts are available for this profile.")
    items.sort(
        key=lambda item: (
            item.get("account_type") != "personal",
            _public_handle(item).casefold(),
        )
    )
    active_account_ref = cfg_mod.current_customer_id(profile_name)
    initial_index = next(
        (
            index
            for index, item in enumerate(items)
            if item.get("account_ref") == active_account_ref
        ),
        0,
    )
    selected_index = select_index(
        item_count=len(items),
        initial_index=initial_index,
        render=lambda index: _render_account_selector(items, index, active_account_ref),
        unavailable_message=(
            "Cannot open account selector. Use `rvs account switch USERNAME_OR_HANDLE`."
        ),
    )
    return items[selected_index]


def _switch_account(account: str | None, profile: str | None) -> None:
    profile_name = _profile_name(profile)
    try:
        selected = (
            resolve_account(account, profile_name)
            if account is not None
            else _select_account_interactive(profile_name)
        )
    except KeyboardInterrupt:
        output.fatal("Account selection cancelled.")
    scope = cfg_mod.account_selection_write_scope()
    saved = cfg_mod.set_active_account(profile=profile_name, customer=selected)
    output.success(f"Account '{display_name(saved)}' selected for {scope}.")
    if os.environ.get("RVS_ACCOUNT_REF"):
        output.warn(
            "RVS_ACCOUNT_REF is set and still overrides the selected account in this shell."
        )


@app.command("switch")
def account_switch(
    account: str | None = typer.Argument(
        None,
        help="Public username or organization handle. Omit to choose interactively.",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Switch to a personal account or organization."""
    _switch_account(account, profile)
