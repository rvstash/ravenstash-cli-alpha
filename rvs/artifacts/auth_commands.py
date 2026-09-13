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
from ..auth.token_format import validate_public_token
from ..client import ApiClient, ApiError
from .discovery import discover
from .formats import flatten_formats


app = typer.Typer(help="Create short-lived tokens for package tools.", no_args_is_help=True)


def duration_seconds(value: str) -> int:
    match = re.fullmatch(r"([0-9]+)(m|h)", value)
    if match is None:
        raise ValueError("Use a duration such as 15m, 30m, 4h, or 12h.")
    seconds = int(match[1]) * (60 if match[2] == "m" else 3600)
    if not 900 <= seconds <= 43200:
        raise ValueError("Temporary credentials support 15 minutes to 12 hours.")
    return seconds


@app.command("mint")
def mint(
    target: str | None = typer.Option(None, "--target", "-t"),
    formats: list[str] | None = typer.Option(
        None, "--format", "-f", help="Comma-separated formats; may also be repeated."
    ),
    all_formats: bool = typer.Option(False, "--all-formats"),
    access: Literal["read", "publish", "admin"] = typer.Option(
        "read",
        "--access",
        help="Admin also permits deletion when your sign-in or automation token allows it.",
    ),
    duration: str = typer.Option(
        "4h", "--duration", help="15m to 12h; source expiry may shorten it."
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    account: str | None = typer.Option(None, "--account"),
) -> None:
    """Print a short-lived token for direct package-tool access.

    Prefer normal rvs package commands when possible. The generated token is secret
    until it expires. This command prints it to stdout; other messages go to stderr.
    """
    try:
        seconds = duration_seconds(duration)
        # Existing account/target helpers may explain context changes. Their
        # diagnostics cannot contaminate a shell-captured bearer value.
        with contextlib.redirect_stdout(sys.stderr):
            requested = flatten_formats(formats or [])
            if all_formats and requested:
                raise ValueError("--all-formats and --format are mutually exclusive.")
            found = discover(
                target, profile, account, requested[0] if len(requested) == 1 else None
            )
            selected = found.target
            if not requested and not all_formats:
                requested = [found.select_format(None)]
            if any(item not in found.formats for item in requested):
                raise ValueError("Every requested format must be enabled on the exact target.")
            client = ApiClient.from_profile(found.profile)
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
                        "registry_kinds": requested or None,
                        "all_formats": all_formats,
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
                        "customer_id": selected.customer_id,
                        "remote_cache_ref": selected.remote_unique_ref,
                        "registry_kind": found.select_format(requested[0] if requested else None),
                        "duration_seconds": seconds,
                    },
                ).json()
        secret = response.get("access_token")
        if not isinstance(secret, str):
            raise ValueError("Ravenstash returned an invalid temporary token.")
        validate_public_token(secret, native=True)
        if output.is_json():
            result = {
                "target": selected.display_selector,
                "formats": response.get("registry_kinds", [response.get("registry_kind")]),
                "access": access,
                "access_token": secret,
                "token_type": response["token_type"],
                "expires_in": response["expires_in"],
            }
            click.echo(json.dumps(result, separators=(",", ":")))
        else:
            click.echo(secret)
    except (ApiError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
