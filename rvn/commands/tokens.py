"""rvn tokens — create and manage repository-scoped API tokens."""

from __future__ import annotations

import typer

from .. import output
from ..client import ApiClient, ApiError


app = typer.Typer(help="Manage repository API tokens.")


def _client(profile: str | None) -> ApiClient:
    return ApiClient.from_profile(profile)


@app.command("list")
def list_tokens(
    repo: str = typer.Argument(..., help="Repository slug"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """List API tokens for a repository."""
    client = _client(profile)
    try:
        data = client.get(f"/webapp/repositories/{repo}/tokens/").json()
    except ApiError as exc:
        output.fatal(str(exc))

    items = data if isinstance(data, list) else data.get("items", [])
    if not items:
        output.info(f"No tokens for '{repo}'.")
        return

    output.table(
        ["ID", "Label", "Write", "Last used", "Created"],
        [
            [
                t.get("id", ""),
                t.get("label", "—"),
                "✓" if t.get("write") else "—",
                t.get("last_used_at", "never"),
                t.get("created_at", ""),
            ]
            for t in items
        ],
        title=f"Tokens for {repo}",
    )


@app.command("create")
def create_token(
    repo: str = typer.Argument(..., help="Repository slug"),
    label: str = typer.Option("", "--label", "-l", help="Human-readable label"),
    write: bool = typer.Option(False, "--write", "-w", help="Grant write (publish) access"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Create a new repository-scoped API token.

    The plain-text token is printed once and never shown again.
    """
    client = _client(profile)
    try:
        payload: dict = {"repository_slug": repo, "write": write}
        if label:
            payload["label"] = label
        t = client.post("/webapp/tokens/", json=payload).json()
    except ApiError as exc:
        output.fatal(str(exc))

    output.success(f"Token created for '{repo}':")
    output.kv(
        {
            "ID": t.get("id", ""),
            "Label": t.get("label", "—"),
            "Write": "yes" if t.get("write") else "no",
            "Token": t.get("token", ""),
        }
    )
    output.warn("Copy this token now — it will not be shown again.")


@app.command("revoke")
def revoke_token(
    token_id: str = typer.Argument(..., help="Token ID to revoke"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Revoke a repository token by ID."""
    if not yes:
        typer.confirm(f"Revoke token '{token_id}'?", abort=True)
    client = _client(profile)
    try:
        client.delete(f"/webapp/tokens/{token_id}/")
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Token '{token_id}' revoked.")
