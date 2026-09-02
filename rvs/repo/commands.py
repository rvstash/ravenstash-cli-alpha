"""First-class repository commands backed exclusively by DevAPI."""

from __future__ import annotations

import typer

from ..pkg import commands as pkg_commands


app = typer.Typer(
    name="repo",
    help="List and manage Ravenstash package repositories.",
    no_args_is_help=True,
)


@app.command("list")
def list_repos(
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id"),
    registry_kind: str | None = typer.Option(None, "--registry-kind", "-k"),
) -> None:
    """List authorized repositories grouped by account and namespace."""
    pkg_commands.repo_list(
        profile=profile,
        customer_id=customer_id,
        kind=registry_kind,
    )


@app.command("create")
def create(
    name: str = typer.Argument(..., help="Repository name."),
    registry_kind: list[str] = typer.Option(
        ...,
        "--registry-kind",
        "-k",
        help="Registry kind to enable; repeat for multiple lanes.",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id"),
    set_default: bool = typer.Option(False, "--default"),
) -> None:
    """Create a repository in the customer's default namespace."""
    pkg_commands.repo_create(
        name=name,
        kind=registry_kind,
        profile=profile,
        customer_id=customer_id,
        set_default=set_default,
    )


@app.command("show")
def show(
    repository: str = typer.Argument(
        ...,
        help="<namespace>/<repository>, stable references, or a unique repository name.",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show stable repository and namespace identity."""
    pkg_commands.repo_show(repo=repository, profile=profile)


@app.command("rename")
def rename(
    repository: str = typer.Argument(...),
    new_name: str = typer.Argument(...),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Rename a repository without changing its stable native reference."""
    pkg_commands.repo_rename(
        repo=repository,
        new_name=new_name,
        profile=profile,
    )


@app.command("delete")
def delete(
    repository: str = typer.Argument(...),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a repository."""
    pkg_commands.repo_delete(repo=repository, profile=profile, yes=yes)
