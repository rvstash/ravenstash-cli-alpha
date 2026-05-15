"""rvn repos — list, create, and delete repositories."""

from __future__ import annotations

import typer

from .. import output
from ..client import ApiClient, ApiError


app = typer.Typer(help="Manage repositories.")


def _client(profile: str | None) -> ApiClient:
    return ApiClient.from_profile(profile)


@app.command("list")
def list_repos(
    profile: str | None = typer.Option(None, "--profile", "-p"),
    kind: str | None = typer.Option(
        None, "--kind", "-k", help="Filter by registry kind: pypi|npm|maven"
    ),
) -> None:
    """List repositories you have access to."""
    client = _client(profile)
    try:
        params = {}
        if kind:
            params["kind"] = kind
        data = client.get("/webapp/repositories/", params=params or None).json()
    except ApiError as exc:
        output.fatal(str(exc))

    items = data if isinstance(data, list) else data.get("items", [])
    if not items:
        output.info("No repositories found.")
        return

    output.table(
        ["Name", "Slug", "Kind", "Packages", "Upstream", "Public ID"],
        [
            [
                r.get("name", ""),
                r.get("slug", ""),
                r.get("kind", ""),
                str(r.get("package_count", "—")),
                "✓" if r.get("upstream_enabled") else "—",
                r.get("public_id", ""),
            ]
            for r in items
        ],
    )


@app.command("create")
def create_repo(
    name: str = typer.Argument(..., help="Human-readable repository name"),
    kind: str = typer.Argument(..., help="Registry kind: pypi | npm | maven"),
    slug: str | None = typer.Option(
        None, "--slug", help="URL slug (auto-derived from name if omitted)"
    ),
    upstream: bool = typer.Option(False, "--upstream", help="Enable upstream passthrough"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Create a new repository."""
    if kind not in ("pypi", "npm", "maven"):
        output.fatal(f"Unknown registry kind '{kind}'. Use: pypi, npm, maven")

    client = _client(profile)
    payload: dict = {"name": name, "kind": kind, "upstream_enabled": upstream}
    if slug:
        payload["slug"] = slug

    try:
        repo = client.post("/webapp/repositories/", json=payload).json()
    except ApiError as exc:
        output.fatal(str(exc))

    output.success(
        f"Repository '{repo['name']}' created (slug: {repo['slug']}, pid: {repo.get('public_id', '?')})"
    )


@app.command("delete")
def delete_repo(
    slug: str = typer.Argument(..., help="Repository slug"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Delete a repository and all its packages."""
    if not yes:
        typer.confirm(
            f"Delete repository '{slug}' and all its packages? This cannot be undone.",
            abort=True,
        )
    client = _client(profile)
    try:
        client.delete(f"/webapp/repositories/{slug}/")
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Repository '{slug}' deleted.")


@app.command("info")
def repo_info(
    slug: str = typer.Argument(..., help="Repository slug"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show details for a repository."""
    client = _client(profile)
    try:
        r = client.get(f"/webapp/repositories/{slug}/").json()
    except ApiError as exc:
        output.fatal(str(exc))

    output.kv(
        {
            "Name": r.get("name", ""),
            "Slug": r.get("slug", ""),
            "Kind": r.get("kind", ""),
            "Public ID": r.get("public_id", ""),
            "Packages": str(r.get("package_count", "—")),
            "Upstream": "enabled" if r.get("upstream_enabled") else "disabled",
            "Created": r.get("created_at", ""),
        },
        title=f"Repository: {slug}",
    )
