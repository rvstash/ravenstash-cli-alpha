"""rvn-demo — simple CLI that fetches public package metadata via httpx.

Try it:
    python -m rvn_demo.main info httpx
    python -m rvn_demo.main info pydantic --json
"""

from __future__ import annotations

import asyncio

import httpx
import typer
from pydantic import BaseModel
from rich import print as rprint
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(help="Demo: fetch PyPI package metadata.", no_args_is_help=True)


class PackageInfo(BaseModel):
    name: str
    version: str
    summary: str
    home_page: str | None = None
    author: str | None = None
    license: str | None = None
    requires_python: str | None = None


async def _fetch(name: str) -> PackageInfo:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"https://pypi.org/pypi/{name}/json")
        resp.raise_for_status()
    data = resp.json()["info"]
    return PackageInfo(
        name=data.get("name", name),
        version=data.get("version", "?"),
        summary=data.get("summary", ""),
        home_page=data.get("home_page"),
        author=data.get("author"),
        license=data.get("license"),
        requires_python=data.get("requires_python"),
    )


@app.command("info")
def info(
    name: str = typer.Argument(..., help="PyPI package name."),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON."),
) -> None:
    """Fetch and display metadata for a public PyPI package."""
    try:
        pkg = asyncio.run(_fetch(name))
    except httpx.HTTPStatusError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    if as_json:
        import json
        typer.echo(json.dumps(pkg.model_dump(), indent=2))
        return

    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_column("key", style="bold dim", no_wrap=True)
    table.add_column("value")
    for field, value in pkg.model_dump().items():
        if value:
            table.add_row(field.replace("_", " ").title(), str(value))

    rprint(Panel(table, title=f"[bold]{pkg.name} {pkg.version}[/]", border_style="cyan"))


@app.command("versions")
def versions(
    name: str = typer.Argument(..., help="PyPI package name."),
    limit: int = typer.Option(10, "--limit", "-n", help="Max number of versions to show."),
) -> None:
    """List recent versions of a public PyPI package."""
    async def _get_versions() -> list[str]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://pypi.org/pypi/{name}/json")
            resp.raise_for_status()
        releases = list(resp.json()["releases"].keys())
        return sorted(releases, reverse=True)[:limit]

    try:
        vers = asyncio.run(_get_versions())
    except httpx.HTTPStatusError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    rprint(f"[bold]{name}[/] — last {len(vers)} versions:")
    for v in vers:
        rprint(f"  [cyan]{v}[/]")


if __name__ == "__main__":
    app()
