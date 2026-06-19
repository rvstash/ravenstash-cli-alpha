"""rvn auth — authentication and registry defaults.

Wraps the core login/logout flow and adds commands to configure per-kind
registry defaults.

    rvn auth login                        # interactive login (default profile)
    rvn auth login --profile work         # login to a named profile
    rvn auth switch                       # choose active profile
    rvn auth logout                       # remove credentials for current profile
    rvn auth add-registry --kind pypi --repo my-pypi
    rvn auth list                         # show all profiles + per-kind overrides
    rvn auth status                       # verify current token against the API
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING

import typer
from rich.live import Live
from rich.markup import escape

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import output
from .login import perform_device_login


if TYPE_CHECKING:
    from collections.abc import Iterator


app = typer.Typer(
    name="auth",
    help="Multi-registry authentication management — login, logout, per-kind overrides.",
    no_args_is_help=True,
)


_KEY_UP = "up"
_KEY_DOWN = "down"
_KEY_ENTER = "enter"
_KEY_CTRL_C = "ctrl-c"
_ESCAPE_SEQUENCE_TIMEOUT_SECONDS = 0.25
_ESCAPE_SEQUENCE_MAX_CHARS = 8


def _current_profile_name(cfg: cfg_mod.RvnConfig) -> str:
    return cfg_mod.current_profile_name(cfg)


def _target_profile(profile: str | None, cfg: cfg_mod.RvnConfig) -> str:
    return profile or _current_profile_name(cfg)


def _require_profile(cfg: cfg_mod.RvnConfig, profile: str) -> None:
    if profile not in cfg.profiles:
        output.fatal(
            f"Profile '{profile}' is not configured. "
            f"Run `rvn auth login --profile {profile}` first."
        )


@contextmanager
def _raw_terminal() -> Iterator[None]:
    if sys.platform == "win32":
        yield
        return

    try:
        import termios
        import tty
    except ImportError:
        yield
        return

    try:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)
    except (OSError, termios.error):
        yield
        return

    try:
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _read_selector_key() -> str:
    if sys.platform == "win32":
        import msvcrt

        key = msvcrt.getwch()
        if key in {"\x00", "\xe0"}:
            code = msvcrt.getwch()
            if code == "H":
                return _KEY_UP
            if code == "P":
                return _KEY_DOWN
        if key in {"\n", "\r"}:
            return _KEY_ENTER
        if key == "\x03":
            return _KEY_CTRL_C
        return key

    key = _read_stdin_char()
    if key == "\x03":
        return _KEY_CTRL_C
    if key in {"\n", "\r"}:
        return _KEY_ENTER
    if key == "\x1b":
        return _selector_key_from_escape_sequence(_read_escape_sequence(key))
    return key


def _read_escape_sequence(first_char: str) -> str:
    import select

    sequence = first_char
    while len(sequence) < _ESCAPE_SEQUENCE_MAX_CHARS:
        if not select.select([_stdin_selector()], [], [], _ESCAPE_SEQUENCE_TIMEOUT_SECONDS)[0]:
            break
        char = _read_stdin_char()
        if not char:
            break
        sequence += char
        if sequence == "\x1bO":
            continue
        if char.isalpha() or char == "~":
            break
    return sequence


def _stdin_fileno() -> int | None:
    try:
        return sys.stdin.fileno()
    except (AttributeError, OSError):
        return None


def _stdin_selector() -> int | object:
    fd = _stdin_fileno()
    return fd if fd is not None else sys.stdin


def _read_stdin_char() -> str:
    fd = _stdin_fileno()
    if fd is None:
        return sys.stdin.read(1)
    try:
        return os.read(fd, 1).decode("utf-8", errors="ignore")
    except OSError:
        return sys.stdin.read(1)


def _selector_key_from_escape_sequence(sequence: str) -> str:
    if sequence in {"\x1b[A", "\x1bOA"}:
        return _KEY_UP
    if sequence in {"\x1b[B", "\x1bOB"}:
        return _KEY_DOWN
    if sequence.startswith("\x1b[") and sequence.endswith("A"):
        return _KEY_UP
    if sequence.startswith("\x1b[") and sequence.endswith("B"):
        return _KEY_DOWN
    return sequence


def _render_profile_selector(
    profiles: list[str],
    selected_index: int,
    active_profile: str,
) -> str:
    lines = [
        "[bold]Select Ravenstash profile[/]",
        "[dim]Use ↑/↓ and ENTER to confirm.[/]",
        "",
    ]
    for index, profile in enumerate(profiles):
        pointer = ">" if index == selected_index else " "
        active = " [dim](active)[/]" if profile == active_profile else ""
        label = f"[bold]{escape(profile)}[/]" if index == selected_index else escape(profile)
        lines.append(f"[cyan]{pointer}[/] {label}{active}")
    return "\n".join(lines)


def _select_profile_interactive(cfg: cfg_mod.RvnConfig) -> str:
    profiles = list(cfg.profiles)
    if not profiles:
        output.fatal("No profiles configured. Run `rvn auth login` first.")
    if not sys.stdin.isatty() or not output.console.is_terminal:
        output.fatal("Cannot open profile selector. Use `rvn auth switch --profile <name>`.")

    active_profile = _current_profile_name(cfg)
    selected_index = profiles.index(active_profile) if active_profile in profiles else 0

    with (
        _raw_terminal(),
        Live(
            _render_profile_selector(profiles, selected_index, active_profile),
            console=output.console,
            refresh_per_second=10,
            transient=True,
        ) as live,
    ):
        while True:
            key = _read_selector_key()
            if key == _KEY_CTRL_C:
                raise KeyboardInterrupt
            if key == _KEY_UP:
                selected_index = (selected_index - 1) % len(profiles)
            elif key == _KEY_DOWN:
                selected_index = (selected_index + 1) % len(profiles)
            elif key == _KEY_ENTER:
                return profiles[selected_index]
            live.update(_render_profile_selector(profiles, selected_index, active_profile))


def _warn_env_profile_override() -> None:
    if os.environ.get("RVN_PROFILE"):
        output.warn("RVN_PROFILE is set and still overrides the default profile in this shell.")


# ── login ─────────────────────────────────────────────────────────────────────


@app.command("login")
def auth_login(
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help="Config profile to write credentials into (default: active profile).",
    ),
    api_url: str | None = typer.Option(
        None, "--api-url", help="Override DevAPI base URL (saved to profile)."
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Suppress the browser-opening hint."
    ),
) -> None:
    """Authenticate and store credentials for a Ravenstash instance.

    \b
        rvn auth login
        rvn auth login --profile work --api-url https://api.mycompany.com
    """
    cfg = cfg_mod.load()
    perform_device_login(
        profile=_target_profile(profile, cfg),
        api_url=api_url,
        no_browser=no_browser,
    )


# ── switch ────────────────────────────────────────────────────────────────────


@app.command("switch")
def auth_switch(
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help="Profile to activate. Omit to choose from an interactive list.",
    ),
) -> None:
    """Switch the active default profile.

    \b
        rvn auth switch
        rvn auth switch --profile work
    """
    cfg = cfg_mod.load()
    try:
        selected_profile = profile or _select_profile_interactive(cfg)
    except KeyboardInterrupt:
        output.fatal("Profile switch cancelled.")

    _require_profile(cfg, selected_profile)
    cfg_mod.set_default_profile(selected_profile)
    output.success(f"Active profile set to '{selected_profile}'.")
    _warn_env_profile_override()


# ── logout ────────────────────────────────────────────────────────────────────


@app.command("logout")
def auth_logout(
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help="Profile to remove credentials from (default: active profile).",
    ),
    all_profiles: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Remove credentials from all configured profiles.",
    ),
) -> None:
    """Remove stored credentials for one or all profiles.

    \b
        rvn auth logout
        rvn auth logout --profile work
        rvn auth logout --all
    """
    if all_profiles and profile:
        output.fatal("Use either `--profile` or `--all`, not both.")

    cfg = cfg_mod.load()
    if all_profiles:
        profiles = list(cfg.profiles)
        if not profiles:
            output.info("No profiles configured.")
            return
        for profile_name in profiles:
            auth_mod.delete_token(profile_name)
        output.success("Credentials removed for all profiles.")
        return

    profile_name = _target_profile(profile, cfg)
    auth_mod.delete_token(profile_name)
    output.success(f"Credentials removed for profile '{profile_name}'.")


# ── delete ────────────────────────────────────────────────────────────────────


@app.command("delete")
def auth_delete(
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help="Profile to delete (default: active profile).",
    ),
    all_profiles: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Delete all configured profiles.",
    ),
) -> None:
    """Delete one or all profiles, including their stored credentials.

    \b
        rvn auth delete
        rvn auth delete --profile work
        rvn auth delete --all
    """
    if all_profiles and profile:
        output.fatal("Use either `--profile` or `--all`, not both.")

    cfg = cfg_mod.load()
    if all_profiles:
        profiles = list(cfg.profiles)
        if not profiles:
            output.info("No profiles configured.")
            return
        for profile_name in profiles:
            auth_mod.delete_token(profile_name)
        cfg_mod.delete_all_profiles()
        output.success("All profiles deleted.")
        _warn_env_profile_override()
        return

    profile_name = _target_profile(profile, cfg)
    _require_profile(cfg, profile_name)
    auth_mod.delete_token(profile_name)
    cfg_mod.delete_profile(profile_name)
    output.success(f"Profile '{profile_name}' deleted.")
    _warn_env_profile_override()


# ── add-registry ──────────────────────────────────────────────────────────────


@app.command("add-registry")
def auth_add_registry(
    kind: str = typer.Option(
        ...,
        "--kind",
        "-k",
        help="Registry kind: pypi | npm | maven",
    ),
    api_url: str | None = typer.Option(
        None,
        "--api-url",
        help="API URL for this registry kind (overrides the active profile URL).",
    ),
    repo: str | None = typer.Option(
        None,
        "--repo",
        "-r",
        help="Default repository slug for this registry kind.",
    ),
) -> None:
    """Configure per-kind registry defaults.

    Use this when you have separate API URLs for different registry kinds, or
    when you want to pin a default repository slug per kind.

    \b
        rvn auth add-registry --kind pypi --api-url https://api.myhost.com --repo my-pypi

        # Just set the default repo for npm, reuse the profile token
        rvn auth add-registry --kind npm --repo my-npm
    """
    allowed = {"pypi", "npm", "maven"}
    if kind not in allowed:
        output.fatal(f"Invalid kind '{kind}'. Must be one of: {', '.join(sorted(allowed))}")

    cfg_mod.set_registry_override(
        kind=kind,  # type: ignore[arg-type]
        api_url=api_url,
        default_repo=repo,
    )

    parts = []
    if api_url:
        parts.append(f"api-url={api_url}")
    if repo:
        parts.append(f"repo={repo}")

    changes = ", ".join(parts) or "(no changes)"
    output.success(f"Registry '{kind}' updated: {changes}")


# ── list ──────────────────────────────────────────────────────────────────────


@app.command("list")
def auth_list() -> None:
    """Show all configured profiles and per-kind registry overrides.

    \b
        rvn auth list
    """
    cfg = cfg_mod.load()

    output.section("Profiles")
    if not cfg.profiles:
        output.info("  (none configured — run `rvn auth login`)")
    else:
        rows: list[list[str]] = []
        active_profile = _current_profile_name(cfg)
        for name, p in cfg.profiles.items():
            default_marker = " (active)" if name == active_profile else ""
            token_source = auth_mod.token_source(name)
            rows.append(
                [
                    f"{name}{default_marker}",
                    p.api_url,
                    p.customer_id or "unknown",
                    token_source or "no",
                ]
            )
        output.table(["Profile", "API URL", "Customer", "Credential source"], rows)

    output.section("Per-kind registry overrides")
    if not cfg.registries:
        output.info("  (none — run `rvn auth add-registry`)")
    else:
        rows = []
        for kind, r in cfg.registries.items():
            rows.append(
                [
                    kind,
                    r.default_repo or "(not set)",
                    r.api_url or "(uses profile)",
                    "(uses profile)",
                ]
            )
        output.table(["Kind", "Default repo", "API URL override", "Token"], rows)


# ── status ────────────────────────────────────────────────────────────────────


@app.command("status")
def auth_status(
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Profile to check (default: active profile)."
    ),
) -> None:
    """Verify the stored token is valid against the API.

    \b
        rvn auth status
        rvn auth status --profile work
    """
    cfg = cfg_mod.load()
    profile_name = _target_profile(profile, cfg)
    p = cfg.active_profile(profile_name)
    token = auth_mod.get_token(profile_name)
    source = auth_mod.token_source(profile_name)

    if not token:
        output.error("No credentials found. Run `rvn auth login`.")
        raise typer.Exit(1)

    output.kv(
        {
            "Profile": profile_name,
            "API URL": p.api_url,
            "Token source": source or "unknown",
            "Credential type": p.credential_type or "unknown",
            "Customer": p.customer_id or "unknown",
            "Expires at": p.expires_at or "not recorded",
        },
        title="Authentication status",
    )
