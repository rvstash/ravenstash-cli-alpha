"""Explicit, secret-only manual native credential output."""

from __future__ import annotations

import contextlib
import json
import re
import sys
from typing import Literal

import click
import httpx
import typer

from .. import output
from ..account.commands import resolve_account
from ..auth.token_format import validate_public_token
from ..client import ApiClient, ApiError
from .targets import resolve_target


app = typer.Typer(
    help="Generate temporary credentials for package tools.", no_args_is_help=True
)


def duration_seconds(value: str) -> int:
    match = re.fullmatch(r"([0-9]+)(m|h)", value)
    if match is None:
        raise ValueError("Use a duration such as 15m, 30m, 4h, or 12h.")
    seconds = int(match[1]) * (60 if match[2] == "m" else 3600)
    if not 900 <= seconds <= 43200:
        raise ValueError("Temporary credentials support 15 minutes to 12 hours.")
    return seconds


@app.command("print-token")
def print_token(
    target: str = typer.Option(
        ..., "--target", help="namespace/repository, mirror:source, or custom-mirror:name."
    ),
    kind: Literal["pypi", "npm", "maven", "container", "helm"] = typer.Option(..., "--kind"),
    access: Literal["read", "publish", "admin"] = typer.Option(
        "read",
        "--access",
        help="Admin also permits deletion when your source token allows it.",
    ),
    duration: str = typer.Option(
        "4h", "--duration", help="15m to 12h; source expiry may shorten it."
    ),
    profile: str | None = typer.Option(None, "--profile"),
    account: str | None = typer.Option(None, "--account"),
    as_json: bool = typer.Option(
        False, "--json", help="Print the secret and its scope/expiry metadata as JSON."
    ),
) -> None:
    """Print one rvs_slt token to stdout for manual native configuration.

    Prefer normal rvs package commands, which handle temporary credentials for you.
    The generated bearer is sensitive until it expires. This command deliberately
    reveals it; diagnostics are written to stderr.
    """
    try:
        seconds = duration_seconds(duration)
        # Existing account/target helpers may explain context changes. Their
        # diagnostics cannot contaminate a shell-captured bearer value.
        with contextlib.redirect_stdout(sys.stderr):
            customer_id = str(resolve_account(account, profile)["customer_id"]) if account else None
            profile_name, owner, selected = resolve_target(
                target, profile=profile, customer_id=customer_id, kind=kind
            )
            client = ApiClient.from_profile(profile_name)
            operations = {
                "read": ["download"],
                "publish": ["download", "upload"],
                "admin": ["download", "upload", "delete"],
            }[access]
            if selected.target_type == "repository":
                response = client.issue_native(
                    "/package-credentials",
                    {
                        "repository_unique_ref": selected.repository_unique_ref,
                        "registry_kind": kind,
                        "operations": operations,
                        "duration_seconds": seconds,
                        "expected_target": {
                            "namespace_unique_ref": selected.namespace_unique_ref,
                            "namespace_name": selected.namespace_name_cache,
                            "namespace_realm": selected.namespace_realm,
                            "repository_unique_ref": selected.repository_unique_ref,
                            "repository_name": selected.repository_name_cache,
                        },
                    },
                ).json()
            else:
                if access != "read":
                    raise ValueError("Private mirrors support read credentials only.")
                response = client.issue_native(
                    "/remote-package-credentials",
                    {
                        "customer_id": owner.customer_id,
                        "remote_cache_ref": selected.remote_unique_ref,
                        "registry_kind": kind,
                        "duration_seconds": seconds,
                    },
                ).json()
        secret = response.get("access_token")
        if not isinstance(secret, str):
            raise ValueError("DevAPI returned an invalid temporary credential format.")
        validate_public_token(secret, native=True)
        if as_json or output.is_json():
            click.echo(json.dumps(response, separators=(",", ":")))
        else:
            click.echo(secret)
    except (ApiError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
