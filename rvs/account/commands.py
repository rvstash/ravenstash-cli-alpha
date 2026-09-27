"""Commands for choosing a personal account or organization."""

from __future__ import annotations

import os

import typer
from rich.markup import escape

from .. import config as cfg_mod
from .. import output
from ..client import ApiClient, ApiError
from ..devapi import collection_all, platform_path
from ..interactive import select_index
from .handles import typed_handle


app = typer.Typer(
    name="account",
    help="Choose the personal account or organization to use.",
    no_args_is_help=True,
)


def _profile_name(profile: str | None) -> str:
    return profile or cfg_mod.current_profile_name()


def accounts(profile: str | None = None) -> list[dict]:
    try:
        items = collection_all(ApiClient.from_profile(profile), platform_path("accounts"))
    except ApiError as exc:
        output.fatal(str(exc))
    except ValueError:
        output.fatal("Ravenstash returned an invalid account list.")
    return [item for item in items if isinstance(item, dict)]


def payload_display_name(account: dict) -> str:
    """Return the typed public handle from an API account or account summary."""
    try:
        return typed_handle(account.get("type"), account.get("handle"))
    except ValueError:
        output.fatal("Ravenstash returned an account without a valid type and public handle.")


def _folded_typed_handle(account: dict) -> str | None:
    try:
        return typed_handle(account.get("type"), account.get("handle")).casefold()
    except ValueError:
        return None


def match_account(items: list[dict], selector: str) -> dict:
    """Return the one account in *items* that *selector* names, without caching it."""
    value = selector.strip()
    if not value:
        output.fatal("Account name cannot be empty.")

    lowered = value.casefold()
    expected_type = None
    if lowered.startswith("user:"):
        expected_type = "personal"
        handle_selector = value[5:].strip()
    elif lowered.startswith("org:"):
        expected_type = "organization"
        handle_selector = value[4:].strip()
    else:
        handle_selector = value
    if not handle_selector:
        output.fatal("Account handle cannot be empty.")
    handle_selector_folded = handle_selector.casefold()
    handle_matches = [
        item
        for item in items
        if isinstance(item.get("handle"), str)
        and item["handle"].casefold() == handle_selector_folded
        and (expected_type is None or item.get("type") == expected_type)
    ]
    if handle_matches:
        matches = handle_matches
    elif lowered == "personal":
        matches = [item for item in items if item.get("type") == "personal"]
    else:
        # Also accept the typed handle shown for an account type rvs does not know yet.
        matches = [
            item
            for item in items
            if value == item.get("ref") or _folded_typed_handle(item) == lowered
        ]
    if not matches:
        output.fatal(f"Account '{selector}' was not found for this profile.")
    if len(matches) > 1:
        refs = ", ".join(str(item.get("ref")) for item in matches)
        output.fatal(
            f"More than one account matches '{selector}'. "
            f"Use one of these account references: {refs}"
        )
    return matches[0]


def resolve_account(selector: str, profile: str | None = None) -> dict:
    selected = match_account(accounts(profile), selector)
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
                "ref": effective_id,
                "type": "personal",
                "organization_role": "owner",
                "authority_revision": None,
            }
        elif customer_id is not None:
            customer = {
                "ref": effective_id,
                "type": "organization",
                "organization_role": None,
                "authority_revision": None,
            }
        else:
            customer = resolve_account(effective_id, profile_name)
    else:
        items = accounts(profile_name)
        personal = [item for item in items if item.get("type") == "personal"]
        if len(personal) != 1:
            output.fatal("No account is selected. Run `rvs account switch`.")
        customer = personal[0]
    return profile_name, cfg_mod.cache_account(
        profile=profile_name,
        customer=customer,
        activate=customer_id is None,
    )


def with_display_name(handle: str, name: object) -> str:
    """Return a typed handle followed by a display name that adds information."""
    if not isinstance(name, str) or not name.strip():
        return handle
    name = name.strip()
    bare_handle = handle.partition(":")[2] or handle
    return handle if name.casefold() == bare_handle.casefold() else f"{handle} ({name})"


def payload_named_display(account: dict) -> str:
    """Return an API account as its typed handle and display name."""
    return with_display_name(payload_display_name(account), account.get("display_name"))


_CREDENTIAL_KINDS = {
    "user_personal": "personal-account PAT",
    "user_organization": "organization-account PAT",
    "organization_workload": "organization automation token",
}


def identity_person(identity: dict) -> tuple[str | None, str | None]:
    """Return the signed-in person's typed handle and name, never an email.

    Organization automation has no person.
    """
    user = identity.get("user")
    if isinstance(user, dict) and isinstance(user.get("handle"), str):
        name = user.get("display_name")
        return typed_handle("personal", user["handle"]), name if isinstance(name, str) else None
    return None, None


def identity_display(identity: object, *, with_token_account: bool = False) -> str:
    """Describe the principal returned by the platform identity endpoint.

    A person is shown by public handle and name, never by sign-in email. An
    organization automation token has no person. Its account is added only when
    *with_token_account* is set, for output that does not show the account itself.
    """
    if not isinstance(identity, dict):
        return "unknown"
    credential = identity.get("credential")
    scenario = credential.get("scenario") if isinstance(credential, dict) else None
    credential_kind = _CREDENTIAL_KINDS.get(str(scenario), "access token") if scenario else None
    token_account = credential.get("account") if isinstance(credential, dict) else None
    if credential_kind and with_token_account and isinstance(token_account, dict):
        credential_kind = f"{credential_kind} for {payload_display_name(token_account)}"
    handle, name = identity_person(identity)
    if handle is None:
        return credential_kind or identity.get("principal_type") or "unknown"
    person = with_display_name(handle, name)
    return f"{person} · {credential_kind}" if credential_kind else person


def display_name(account: cfg_mod.AccountContext) -> str:
    return typed_handle(
        account.account_type,
        account.customer_handle or account.customer_unique_ref,
    )


@app.command("list")
def account_list(
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """List personal accounts and organizations available to one profile."""
    profile_name = _profile_name(profile)
    active_id = cfg_mod.current_customer_id(profile_name)
    rows = []
    for item in accounts(profile_name):
        account_ref = str(item.get("ref", ""))
        label = payload_display_name(item)
        rows.append(
            [
                f"{label} (active)" if account_ref == active_id else label,
                str(item.get("display_name") or ""),
                account_ref,
                str(item.get("organization_role") or ""),
            ]
        )
    output.table(["Account", "Name", "Account ref", "Role"], rows)


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
        handle = escape(output.plain(payload_display_name(item)))
        account_ref = str(item.get("ref", ""))
        account_type = item.get("type")
        role = str(item.get("organization_role") or "")
        kind = {"personal": "Personal", "organization": "Organization"}.get(
            str(account_type), str(account_type)
        )
        detail = f"{kind} · {role}" if role else kind
        active = " [dim](active)[/]" if account_ref == active_account_ref else ""
        pointer = ">" if index == selected_index else " "
        label = f"[bold]{handle}[/]" if index == selected_index else handle
        lines.append(f"[cyan]{pointer}[/] {label} [dim]{escape(output.plain(detail))}[/]{active}")
    return "\n".join(lines)


def _select_account_interactive(profile_name: str) -> dict:
    items = accounts(profile_name)
    if not items:
        output.fatal("No accounts are available for this profile.")
    items.sort(
        key=lambda item: (
            item.get("type") != "personal",
            payload_display_name(item).casefold(),
        )
    )
    active_account_ref = cfg_mod.current_customer_id(profile_name)
    initial_index = next(
        (index for index, item in enumerate(items) if item.get("ref") == active_account_ref),
        0,
    )
    selected_index = select_index(
        item_count=len(items),
        initial_index=initial_index,
        render=lambda index: _render_account_selector(items, index, active_account_ref),
        unavailable_message=(
            "Cannot open account selector. Use `rvs account switch user:USERNAME` "
            "or `rvs account switch org:HANDLE`."
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
        help=(
            "Typed user or organization handle (user:USERNAME or org:HANDLE). "
            "Bare handles remain supported. Omit to choose interactively."
        ),
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Switch to a personal account or organization."""
    _switch_account(account, profile)
