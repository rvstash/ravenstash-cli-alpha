"""rvn config — view and edit the rvn configuration file."""

from __future__ import annotations

import typer

from .. import config as cfg_mod
from .. import output


app = typer.Typer(help="Manage rvn configuration.")


@app.command("show")
def show(
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Profile to show (default: active profile)."
    ),
) -> None:
    """Print the active profile configuration."""
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    active = profile or cfg.default_profile
    output.kv(
        {
            "Profile": active,
            "API URL": p.api_url,
            "Credential source": _credential_source(active) or "no",
            "Customer": p.customer_id or "—",
            "Credential type": p.credential_type or "—",
            "Expires at": p.expires_at or "—",
            "Config file": str(cfg_mod.CONFIG_FILE),
        },
        title="Active configuration",
    )
    regs = cfg.registries
    if regs:
        output.kv(
            {f"registries.{k}.default_repo": v.default_repo or "—" for k, v in regs.items()},
            title="Registry defaults",
        )


@app.command("set-api-url")
def set_api_url(
    url: str = typer.Argument(..., help="API base URL, e.g. https://api.ravenstash.com"),
    profile: str = typer.Option("default", "--profile", "-p"),
) -> None:
    """Set the API base URL for a profile."""
    cfg_mod.set_profile_value(profile, api_url=url)
    output.success(f"API URL for profile '{profile}' set to {url}")


@app.command("set-default-repo")
def set_default_repo(
    kind: str = typer.Argument(..., help="Registry kind: pypi | npm | maven"),
    repo: str = typer.Argument(..., help="Repository slug"),
    profile: str = typer.Option("default", "--profile", "-p"),
) -> None:
    """Set the default repository for a registry kind."""
    if kind not in ("pypi", "npm", "maven"):
        output.fatal(f"Unknown registry kind '{kind}'. Use: pypi, npm, maven")
    cfg_mod.set_registry_default_repo(kind, repo)  # type: ignore[arg-type]
    output.success(f"Default {kind} repository set to '{repo}'")


@app.command("use-profile")
def use_profile(
    profile: str = typer.Argument(..., help="Profile name to activate"),
) -> None:
    """Switch the active default profile."""
    cfg_mod.set_default_profile(profile)
    output.success(f"Default profile set to '{profile}'")


@app.command("list-profiles")
def list_profiles() -> None:
    """List all configured profiles."""
    cfg = cfg_mod.load()
    rows = [
        [
            name,
            p.api_url,
            "✓" if name == cfg.default_profile else "",
        ]
        for name, p in cfg.profiles.items()
    ]
    if not rows:
        output.info("No profiles configured. Run: rvn auth login")
        return
    output.table(["Profile", "API URL", "Active"], rows)


# ── helpers ───────────────────────────────────────────────────────────────────


def _credential_source(profile: str) -> str | None:
    from .. import auth as auth_mod

    return auth_mod.token_source(profile)
