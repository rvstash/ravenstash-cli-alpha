"""rvn packages — browse packages and versions inside a repository."""

from __future__ import annotations

import typer

from .. import output
from ..client import ApiClient, ApiError


app = typer.Typer(help="Browse packages inside repositories.")


def _client(profile: str | None) -> ApiClient:
    return ApiClient.from_profile(profile)


@app.command("list")
def list_packages(
    repo: str = typer.Argument(..., help="Repository slug"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """List packages in a repository."""
    client = _client(profile)
    try:
        data = client.get(f"/webapp/repositories/{repo}/packages/", params={"limit": limit}).json()
    except ApiError as exc:
        output.fatal(str(exc))

    items = data if isinstance(data, list) else data.get("items", [])
    if not items:
        output.info(f"No packages in '{repo}'.")
        return

    output.table(
        ["Name", "Latest version", "Downloads", "Updated"],
        [
            [
                p.get("name", ""),
                p.get("latest_version", "—"),
                str(p.get("download_count", "—")),
                p.get("updated_at", "—"),
            ]
            for p in items
        ],
        title=f"Packages in {repo}",
    )


@app.command("info")
def package_info(
    repo: str = typer.Argument(..., help="Repository slug"),
    package: str = typer.Argument(..., help="Package name"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show package details and version list."""
    client = _client(profile)
    try:
        p = client.get(f"/webapp/repositories/{repo}/packages/{package}/").json()
    except ApiError as exc:
        output.fatal(str(exc))

    output.kv(
        {
            "Name": p.get("name", ""),
            "Latest": p.get("latest_version", "—"),
            "Downloads": str(p.get("download_count", "—")),
            "Summary": p.get("summary") or "—",
            "License": p.get("license") or "—",
        },
        title=f"{package} @ {repo}",
    )

    versions = p.get("versions", [])
    if versions:
        output.table(
            ["Version", "Filename", "Size", "Uploaded"],
            [
                [
                    v.get("version", ""),
                    v.get("filename", ""),
                    _fmt_size(v.get("size_bytes")),
                    v.get("created_at", "—"),
                ]
                for v in versions
            ],
        )


@app.command("delete")
def delete_package(
    repo: str = typer.Argument(..., help="Repository slug"),
    package: str = typer.Argument(..., help="Package name"),
    version: str | None = typer.Option(
        None, "--version", "-v", help="Delete a specific version only"
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a package or a specific version from a repository."""
    target = f"{package}@{version}" if version else package
    if not yes:
        typer.confirm(f"Delete {target} from '{repo}'?", abort=True)

    client = _client(profile)
    try:
        if version:
            client.delete(f"/webapp/repositories/{repo}/packages/{package}/versions/{version}/")
        else:
            client.delete(f"/webapp/repositories/{repo}/packages/{package}/")
    except ApiError as exc:
        output.fatal(str(exc))

    output.success(f"Deleted {target} from '{repo}'.")


# ── helpers ───────────────────────────────────────────────────────────────────


def _fmt_size(b: int | None) -> str:
    if b is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f} {unit}"
        b //= 1024
    return f"{b} TB"
