"""`rvs auth` command group."""

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
from ..client import ApiClient, ApiError
from .device import perform_device_login


if TYPE_CHECKING:
    from collections.abc import Iterator


app = typer.Typer(
    name="auth",
    help="Authenticate with Ravenstash and manage local profiles.",
    no_args_is_help=True,
)
profile_app = typer.Typer(
    name="profile",
    help="Manage local authenticated profiles.",
    no_args_is_help=True,
)
app.add_typer(profile_app, name="profile")

_KEY_UP = "up"
_KEY_DOWN = "down"
_KEY_ENTER = "enter"
_KEY_CTRL_C = "ctrl-c"
_ESCAPE_SEQUENCE_TIMEOUT_SECONDS = 0.25
_ESCAPE_SEQUENCE_MAX_CHARS = 8


def _current_profile_name(cfg: cfg_mod.RvsConfig) -> str:
    return cfg_mod.current_profile_name(cfg)


def _target_profile(profile: str | None, cfg: cfg_mod.RvsConfig) -> str:
    return profile or _current_profile_name(cfg)


def _require_profile(cfg: cfg_mod.RvsConfig, profile: str) -> None:
    if profile not in cfg.profiles:
        output.fatal(
            f"Profile '{profile}' is not configured. "
            f"Run `rvs auth login --profile {profile}` first."
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
        "[dim]Use up/down and ENTER to confirm.[/]",
        "",
    ]
    for index, profile in enumerate(profiles):
        pointer = ">" if index == selected_index else " "
        active = " [dim](active)[/]" if profile == active_profile else ""
        label = f"[bold]{escape(profile)}[/]" if index == selected_index else escape(profile)
        lines.append(f"[cyan]{pointer}[/] {label}{active}")
    return "\n".join(lines)


def _select_profile_interactive(cfg: cfg_mod.RvsConfig) -> str:
    profiles = list(cfg.profiles)
    if not profiles:
        output.fatal("No profiles configured. Run `rvs auth login` first.")
    if not sys.stdin.isatty() or not output.console.is_terminal:
        output.fatal("Cannot open profile selector. Use `rvs auth profile switch <name>`.")

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
    if os.environ.get("RVS_PROFILE"):
        output.warn("RVS_PROFILE is set and still overrides the default profile in this shell.")


@app.command("login")
def login(
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help="Profile to write credentials into (default: active profile).",
    ),
    api_url: str | None = typer.Option(
        None, "--api-url", help="Override DevAPI base URL and save it to the profile."
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Suppress the browser-opening hint."
    ),
    duration: str | None = typer.Option(
        None,
        "--duration",
        help="Requested device session duration, for example 8h or 3days.",
    ),
) -> None:
    """Authenticate through Ravenstash browser/device login."""
    cfg = cfg_mod.load()
    perform_device_login(
        profile=_target_profile(profile, cfg),
        api_url=api_url,
        no_browser=no_browser,
        duration=duration,
    )


@app.command("logout")
def logout(
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
    """Remove stored credentials without deleting profile metadata."""
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


@app.command("status")
def status(
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Profile to inspect (default: active profile)."
    ),
) -> None:
    """Show the local authentication state for a profile."""
    cfg = cfg_mod.load()
    profile_name = _target_profile(profile, cfg)
    p = cfg.active_profile(profile_name)
    token = auth_mod.get_token(profile_name)
    source = auth_mod.token_source(profile_name)

    output.kv(
        {
            "Profile": profile_name,
            "API URL": p.api_url,
            "Package download URL": p.pkg_download_url,
            "Package upload URL": p.pkg_upload_url,
            "Authenticated": "yes" if token else "no",
            "Credential source": source or "none",
            "Credential type": auth_mod.display_credential_type(p.credential_type) or "unknown",
            "Owner ID": p.customer_id or "unknown",
            "Access expires at": p.expires_at or "unknown",
            "Refresh expires at": p.refresh_expires_at or "unknown",
        },
        title="Authentication status",
    )
    if not token:
        raise typer.Exit(1)


@app.command("whoami")
def whoami(
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Profile to inspect (default: active profile)."
    ),
) -> None:
    """Verify and print the current identity using the package control API."""
    cfg = cfg_mod.load()
    profile_name = _target_profile(profile, cfg)
    p = cfg.active_profile(profile_name)
    try:
        identity = ApiClient.from_profile(profile_name).get("/v0/me").json()
    except ApiError as exc:
        output.fatal(f"Could not verify the current identity: {exc}")
    output.kv(
        {
            "Profile": profile_name,
            "User": identity.get("email") or identity.get("id") or "unknown",
            "Owner ID": identity.get("customer_id") or "unknown",
            "Owner": identity.get("customer_unique_id") or "unknown",
            "API URL": p.api_url,
            "Package download URL": p.pkg_download_url,
            "Package upload URL": p.pkg_upload_url,
        },
        title="Current Ravenstash identity",
    )


@profile_app.command("list")
def profile_list() -> None:
    """List configured local profiles."""
    cfg = cfg_mod.load()
    if not cfg.profiles:
        output.info("No profiles configured. Run `rvs auth login` first.")
        return

    active_profile = _current_profile_name(cfg)
    rows: list[list[str]] = []
    for name, p in cfg.profiles.items():
        rows.append(
            [
                f"{name} (active)" if name == active_profile else name,
                p.api_url,
                p.customer_id or "unknown",
                auth_mod.token_source(name) or "none",
            ]
        )
    output.table(["Profile", "API URL", "Owner ID", "Credential source"], rows)


@profile_app.command("switch")
def profile_switch(
    profile: str | None = typer.Argument(
        None,
        help="Profile to activate. Omit to choose from an interactive list.",
    ),
) -> None:
    """Switch the active default profile."""
    cfg = cfg_mod.load()
    try:
        selected_profile = profile or _select_profile_interactive(cfg)
    except KeyboardInterrupt:
        output.fatal("Profile switch cancelled.")

    _require_profile(cfg, selected_profile)
    cfg_mod.set_default_profile(selected_profile)
    output.success(f"Active profile set to '{selected_profile}'.")
    _warn_env_profile_override()


@profile_app.command("delete")
def profile_delete(
    profile: str | None = typer.Argument(
        None,
        help="Profile to delete (default: active profile).",
    ),
    all_profiles: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Delete all configured profiles.",
    ),
) -> None:
    """Delete one or all profiles, including stored credentials."""
    if all_profiles and profile:
        output.fatal("Use either a profile name or `--all`, not both.")

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

    profile_name = profile or _current_profile_name(cfg)
    _require_profile(cfg, profile_name)
    auth_mod.delete_token(profile_name)
    cfg_mod.delete_profile(profile_name)
    output.success(f"Profile '{profile_name}' deleted.")
    _warn_env_profile_override()


@profile_app.command("rename")
def profile_rename(
    old: str = typer.Argument(..., help="Existing profile name."),
    new: str = typer.Argument(..., help="New profile name."),
) -> None:
    """Rename a configured profile.

    Stored keyring credentials cannot be renamed portably, so this command moves
    local metadata and asks the user to log in again for the renamed profile.
    """
    cfg = cfg_mod.load()
    _require_profile(cfg, old)
    if new in cfg.profiles:
        output.fatal(f"Profile '{new}' already exists.")

    profile = cfg.profiles[old]
    cfg.profiles[new] = profile
    del cfg.profiles[old]
    if cfg.default_profile == old:
        cfg.default_profile = new
    cfg_mod.save(cfg)
    auth_mod.delete_token(old)
    output.success(f"Profile '{old}' renamed to '{new}'.")
    output.info(
        f"Run `rvs auth login --profile {new}` to store credentials for the renamed profile."
    )
