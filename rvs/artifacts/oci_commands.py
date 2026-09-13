"""OCI graph management through the typed developer API."""

from __future__ import annotations

import contextlib
import json
import sys
from typing import Literal
from urllib.parse import quote

import click
import httpx
import typer

from .. import output
from ..client import ApiClient, ApiError
from ..oci.reference import qualify_reference
from .discovery import discover


app = typer.Typer(help="Manage OCI paths, manifests, tags and referrers.", no_args_is_help=True)
manifest_app = typer.Typer(no_args_is_help=True)
tag_app = typer.Typer(no_args_is_help=True)
referrer_app = typer.Typer(no_args_is_help=True)
app.add_typer(manifest_app, name="manifest")
app.add_typer(tag_app, name="tag")
app.add_typer(referrer_app, name="referrer")


def _reference(value: str, kind: str) -> tuple[str, str]:
    qualify_reference("unused", value)
    separator = "@" if kind == "digest" else ":"
    path, found, reference = value.partition(separator)
    if not found or (kind == "tag" and "@" in value):
        raise ValueError(f"Use PATH{'@sha256:DIGEST' if kind == 'digest' else ':TAG'}.")
    return path, reference


def _path(value: str) -> str:
    qualify_reference("unused", value)
    if "@" in value or ":" in value:
        raise ValueError("Use an OCI path without a tag, digest, or registry URL.")
    return value


def _request(
    method: str,
    suffix: str,
    *,
    target: str | None,
    account: str | None,
    profile: str | None,
    params: dict | None = None,
    body: dict | None = None,
    yes: bool = False,
) -> None:
    try:
        with contextlib.redirect_stdout(sys.stderr):
            found = discover(target, profile, account, "oci")
            found.select_format("oci")
            if found.target.target_type != "repository":
                raise ValueError("OCI commands require a repository target.")
            reference = found.target.repository_unique_ref
            if not reference:
                raise ValueError("The selected repository has no stable reference.")
            client = ApiClient.from_profile(found.profile)
            url = f"/repositories/{quote(reference, safe='')}/oci/{suffix}"
            if method == "DELETE" and not yes:
                typer.confirm(f"Delete {params} from {found.target.display_selector}?", abort=True)
            if method == "GET":
                response = client.get(
                    url,
                    params={
                        key: value for key, value in (params or {}).items() if value is not None
                    },
                )
            elif method == "POST":
                response = client.post(url, json=body)
            else:
                response = client.delete(url, params=params)
            payload = response.json()
        if output.is_json():
            click.echo(json.dumps(payload))
        elif "items" in payload:
            rows = payload["items"]
            columns = [
                key
                for key in ("path", "content_type", "digest", "tag", "manifest_kind", "tag_count")
                if any(key in row for row in rows)
            ]
            output.table(columns, [[str(row.get(key) or "—") for key in columns] for row in rows])
            if payload.get("next_cursor"):
                click.echo(f"Next page: --cursor {payload['next_cursor']}", err=True)
        else:
            output.kv(
                {
                    key: json.dumps(value) if isinstance(value, (list, dict)) else str(value)
                    for key, value in payload.items()
                }
            )
    except (ApiError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        output.fatal(str(exc))


def _validated(call, *args):
    try:
        return call(*args)
    except ValueError as exc:
        output.fatal(str(exc))


@app.command("list")
def list_paths(
    content_type: Literal["container_image", "helm_chart"] | None = typer.Option(
        None, "--content-type"
    ),
    search: str | None = typer.Option(None, "--search"),
    limit: int = typer.Option(50, "--limit", min=1, max=100),
    cursor: str | None = typer.Option(None, "--cursor"),
    target: str | None = typer.Option(None, "--target", "-t"),
    account: str | None = typer.Option(None, "--account"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    _request(
        "GET",
        "paths",
        target=target,
        account=account,
        profile=profile,
        params={"content_type": content_type, "search": search, "limit": limit, "cursor": cursor},
    )


@app.command("show")
def show_path(
    path: str = typer.Argument(...),
    target: str | None = typer.Option(None, "--target", "-t"),
    account: str | None = typer.Option(None, "--account"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    _request(
        "GET",
        "paths/detail",
        target=target,
        account=account,
        profile=profile,
        params={"path": _validated(_path, path)},
    )


@manifest_app.command("list")
def manifest_app_list(
    path: str = typer.Argument(...),
    limit: int = typer.Option(50, "--limit", min=1, max=100),
    cursor: str | None = typer.Option(None, "--cursor"),
    target: str | None = typer.Option(None, "--target", "-t"),
    account: str | None = typer.Option(None, "--account"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    path = _validated(_path, path)
    _request(
        "GET",
        "manifests",
        target=target,
        account=account,
        profile=profile,
        params={"path": path, "limit": limit, "cursor": cursor},
    )


@manifest_app.command("show")
def manifest_app_show(
    reference: str = typer.Argument(...),
    target: str | None = typer.Option(None, "--target", "-t"),
    account: str | None = typer.Option(None, "--account"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    path, digest = _validated(_reference, reference, "digest")
    _request(
        "GET",
        f"manifests/{quote(digest, safe='')}",
        target=target,
        account=account,
        profile=profile,
        params={"path": path},
    )


@manifest_app.command("delete")
def manifest_app_delete(
    reference: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
    target: str | None = typer.Option(None, "--target", "-t"),
    account: str | None = typer.Option(None, "--account"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    path, digest = _validated(_reference, reference, "digest")
    _request(
        "DELETE",
        f"manifests/{quote(digest, safe='')}",
        target=target,
        account=account,
        profile=profile,
        params={"path": path},
        yes=yes,
    )


@tag_app.command("list")
def tag_app_list(
    path: str = typer.Argument(...),
    limit: int = typer.Option(50, "--limit", min=1, max=100),
    cursor: str | None = typer.Option(None, "--cursor"),
    target: str | None = typer.Option(None, "--target", "-t"),
    account: str | None = typer.Option(None, "--account"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    path = _validated(_path, path)
    _request(
        "GET",
        "tags",
        target=target,
        account=account,
        profile=profile,
        params={"path": path, "limit": limit, "cursor": cursor},
    )


@tag_app.command("delete")
def tag_app_delete(
    reference: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
    target: str | None = typer.Option(None, "--target", "-t"),
    account: str | None = typer.Option(None, "--account"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    path, tag = _validated(_reference, reference, "tag")
    _request(
        "DELETE",
        "tags",
        target=target,
        account=account,
        profile=profile,
        params={"path": path, "tag": tag},
        yes=yes,
    )


@referrer_app.command("list")
def referrer_app_list(
    reference: str = typer.Argument(...),
    limit: int = typer.Option(50, "--limit", min=1, max=100),
    cursor: str | None = typer.Option(None, "--cursor"),
    target: str | None = typer.Option(None, "--target", "-t"),
    account: str | None = typer.Option(None, "--account"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    path, digest = _validated(_reference, reference, "digest")
    _request(
        "GET",
        "referrers",
        target=target,
        account=account,
        profile=profile,
        params={"path": path, "limit": limit, "cursor": cursor, "digest": digest},
    )


@tag_app.command("create")
def create_tag(
    reference: str = typer.Argument(..., help="PATH@sha256:DIGEST"),
    tag: str = typer.Argument(...),
    target: str | None = typer.Option(None, "--target", "-t"),
    account: str | None = typer.Option(None, "--account"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    path, digest = _validated(_reference, reference, "digest")
    _validated(qualify_reference, "unused", f"{path}:{tag}")
    _request(
        "POST",
        "tags",
        target=target,
        account=account,
        profile=profile,
        body={"path": path, "digest": digest, "tag": tag},
    )
