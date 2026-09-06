"""`rvs auth` command group."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING

import typer
from click import Choice
from rich.live import Live
from rich.markup import escape

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import output
from ..client import ApiClient, ApiError
from . import stores
from .device import perform_device_login


if TYPE_CHECKING:
    from collections.abc import Iterator


app = typer.Typer(
    name="auth",
    help="Authenticate a Ravenstash user and manage local credentials.",
    no_args_is_help=True,
)
profile_app = typer.Typer(
    name="profile",
    help="Manage named local CLI profiles.",
    no_args_is_help=True,
)
storage_app = typer.Typer(
    name="storage",
    help="Set up, select, and diagnose credential storage.",
    no_args_is_help=True,
)
app.add_typer(storage_app, name="storage")

_KEY_UP = "up"
_KEY_DOWN = "down"
_KEY_ENTER = "enter"
_KEY_CTRL_C = "ctrl-c"
_ESCAPE_SEQUENCE_TIMEOUT_SECONDS = 0.25
_ESCAPE_SEQUENCE_MAX_CHARS = 8
_DEDICATED_STORE_LABEL = "Ravenstash encrypted vault"
_DEDICATED_STORE_PROMPT = "Install a dedicated credential store for rvs?"


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


def _repository_status_fields(
    endpoints: cfg_mod.NativeRegistryEndpoints,
    *,
    verbose: bool,
) -> dict[str, str]:
    fields = {"Repository domain": cfg_mod.repository_domain_summary(endpoints)}
    if verbose:
        fields.update(
            {
                "PyPI read URL": endpoints.pypi.read_base_url,
                "PyPI push URL": endpoints.pypi.push_base_url,
                "PyPI mirror URL": endpoints.pypi.mirror_base_url,
                "npm read URL": endpoints.npm.read_base_url,
                "npm push URL": endpoints.npm.push_base_url,
                "npm mirror URL": endpoints.npm.mirror_base_url,
                "Maven read URL": endpoints.maven.read_base_url,
                "Maven push URL": endpoints.maven.push_base_url,
                "Maven mirror URL": endpoints.maven.mirror_base_url,
                "OCI registry URL": endpoints.oci_registry_base_url,
            }
        )
    return fields


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
    except OSError, termios.error:
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
    except AttributeError, OSError:
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
        "[bold]Select local Ravenstash profile[/]",
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
        output.fatal("Cannot open profile selector. Use `rvs profile use <name>`.")

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


def _interactive_terminal_available() -> bool:
    return sys.stdin.isatty() and output.console.is_terminal and not output.is_json()


def _warn_if_short_vault_passphrase(passphrase: str) -> None:
    if (
        stores.vault.MIN_PASSPHRASE_LENGTH
        <= len(passphrase)
        < stores.vault.RECOMMENDED_PASSPHRASE_LENGTH
    ):
        output.warn(
            f"This passphrase is accepted, but {stores.vault.RECOMMENDED_PASSPHRASE_LENGTH}+ "
            "characters or a short multi-word passphrase is recommended."
        )


def _initialize_vault_interactively() -> str:
    if stores.vault.exists():
        if not stores.vault.agent_running():
            credential_storage_unlock()
        return "vault"
    if not _interactive_terminal_available():
        output.fatal(
            "The encrypted vault must be initialized in an interactive terminal. "
            "Run `rvs auth storage setup --store vault`."
        )
    passphrase = typer.prompt(
        "New Ravenstash vault passphrase (8 character minimum; 12+ recommended)",
        hide_input=True,
    )
    confirmation = typer.prompt("Confirm vault passphrase", hide_input=True)
    if passphrase != confirmation:
        output.fatal("Vault passphrases do not match.")
    _warn_if_short_vault_passphrase(passphrase)
    try:
        stores.vault.initialize(passphrase)
    except stores.vault.VaultError as exc:
        output.fatal(str(exc))
    output.success("Encrypted Ravenstash credential vault initialized and unlocked.")
    return "vault"


def _initialize_plaintext(*, allow_insecure_storage: bool) -> str:
    output.warn(
        "PLAINTEXT STORAGE IS NOT ENCRYPTED. Any process or person able to read your "
        "Linux home directory can copy the Ravenstash access and refresh tokens."
    )
    if stores.plaintext_store.exists():
        output.warn(
            f"Using existing plaintext credential storage at {stores.plaintext_store.path()}."
        )
        return "plaintext"
    if not allow_insecure_storage:
        if not _interactive_terminal_available():
            output.fatal(
                "Plaintext storage requires interactive acknowledgement or both "
                "`--credential-store plaintext` and `--allow-insecure-storage`."
            )
        acknowledgement = typer.prompt("Type STORE PLAINTEXT to accept this risk")
        if acknowledgement != "STORE PLAINTEXT":
            output.fatal("Plaintext credential storage was not enabled.")
    try:
        stores.plaintext_store.initialize()
    except stores.plaintext_store.PlaintextStoreError as exc:
        output.fatal(str(exc))
    output.warn(f"Plaintext credential storage enabled at {stores.plaintext_store.path()}.")
    return "plaintext"


def _configure_local_store(
    requested: str | None,
    *,
    allow_insecure_storage: bool,
    first_login: bool = False,
) -> str:
    normalized = (requested or "auto").strip().lower()
    if normalized not in {"auto", "vault", "plaintext"}:
        output.fatal(
            f"Credential store '{normalized}' is unavailable. Configure it first or run "
            "`rvs auth storage setup` to initialize the encrypted vault."
        )
    if normalized == "auto":
        if not _interactive_terminal_available():
            output.fatal(
                "No credential store is configured. Run `rvs auth storage setup` "
                "interactively or use RVS_TOKEN for automation."
            )
        output.warn("No usable OS keyring or initialized pass store was detected.")
        if first_login:
            if not typer.confirm(_DEDICATED_STORE_PROMPT, default=True):
                output.fatal(
                    "Login requires credential storage. Configure a store with "
                    "`rvs auth storage setup` and try again."
                )
            normalized = "vault"
        else:
            normalized = typer.prompt(
                "Credential storage",
                default="vault",
                type=Choice(["vault", "plaintext", "cancel"], case_sensitive=False),
                show_choices=True,
            ).lower()
            if normalized == "cancel":
                output.fatal("Credential-storage setup was cancelled.")
    selected = (
        _initialize_vault_interactively()
        if normalized == "vault"
        else _initialize_plaintext(allow_insecure_storage=allow_insecure_storage)
    )
    cfg_mod.set_credential_store(selected)
    if first_login:
        output.success(f"Installed dedicated credential store: {_DEDICATED_STORE_LABEL}.")
    return selected


@app.command("login")
def login(
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help="Local profile to write credentials into (default: selected profile).",
    ),
    api_url: str | None = typer.Option(
        None,
        "--api-url",
        hidden=True,
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Suppress the browser-opening hint."
    ),
    duration: str | None = typer.Option(
        None,
        "--duration",
        help="Requested device session duration (12 hours to 180 days; default 180 days).",
    ),
    credential_store: str | None = typer.Option(
        None,
        "--credential-store",
        help="Store for this login: auto, keyring, pass, vault, or plaintext.",
    ),
    allow_insecure_storage: bool = typer.Option(
        False,
        "--allow-insecure-storage",
        help="Acknowledge plaintext token storage for a non-interactive setup.",
    ),
) -> None:
    """Authenticate through Ravenstash browser/device login."""
    cfg = cfg_mod.load()
    profile_name = _target_profile(profile, cfg)
    try:
        selected_store = auth_mod.preflight_credential_store(profile_name, credential_store)
    except auth_mod.NoCredentialStoreError:
        selected_store = _configure_local_store(
            auth_mod.credential_store_preference(profile_name, credential_store),
            allow_insecure_storage=allow_insecure_storage,
            first_login=True,
        )
        try:
            selected_store = auth_mod.preflight_credential_store(profile_name, selected_store)
        except RuntimeError as exc:
            output.fatal(str(exc))
    except RuntimeError as exc:
        output.fatal(str(exc))
    perform_device_login(
        profile=profile_name,
        api_url=api_url,
        no_browser=no_browser,
        duration=duration,
        credential_store=selected_store,
    )


@storage_app.command("doctor")
def keyring_doctor(
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Local profile whose store selection should be resolved."
    ),
) -> None:
    """Diagnose supported credential stores without exposing credentials."""
    cfg = cfg_mod.load()
    profile_name = _target_profile(profile, cfg)
    statuses = auth_mod.credential_store_statuses()
    try:
        selected = auth_mod.preflight_credential_store(profile_name)
        selection_error = None
        round_trip = "passed"
    except RuntimeError as exc:
        selected = None
        selection_error = str(exc)
        round_trip = "not available"

    rows = [
        [
            status.name,
            "yes" if status.available else "no",
            status.backend,
            status.detail,
        ]
        for status in statuses
    ]
    output.table(["Store", "Available", "Backend", "Detail"], rows, title="Credential stores")
    output.kv(
        {
            "Profile": profile_name,
            "Configured preference": os.environ.get("RVS_CREDENTIAL_STORE") or cfg.credential_store,
            "Selected store": selected or "none",
            "Write/read/delete check": round_trip,
            "RVS_TOKEN set": "yes" if os.environ.get("RVS_TOKEN") else "no",
            "Selection error": selection_error,
        }
    )
    if selected is None:
        raise typer.Exit(1)


@storage_app.command("setup")
def credential_storage_setup(
    store: str | None = typer.Option(
        None,
        "--store",
        help="Local fallback to initialize: vault or plaintext (default: prompt).",
    ),
    allow_insecure_storage: bool = typer.Option(
        False,
        "--allow-insecure-storage",
        help="Acknowledge plaintext token storage for a non-interactive setup.",
    ),
) -> None:
    """Initialize credential storage before the first device login."""
    selected = _configure_local_store(
        store,
        allow_insecure_storage=allow_insecure_storage,
    )
    try:
        auth_mod.preflight_credential_store(cfg_mod.current_profile_name(cfg_mod.load()), selected)
    except RuntimeError as exc:
        output.fatal(str(exc))
    output.success(f"Credential storage is ready using '{selected}'.")


@storage_app.command("unlock")
def credential_storage_unlock() -> None:
    """Unlock the encrypted vault for this Linux login session."""
    if not stores.vault.exists():
        output.fatal("Encrypted Ravenstash vault is not initialized.")
    if stores.vault.agent_running():
        output.info("Encrypted Ravenstash vault is already unlocked.")
        return
    if not _interactive_terminal_available():
        output.fatal("Vault unlock requires an interactive terminal.")
    passphrase = typer.prompt("Ravenstash vault passphrase", hide_input=True)
    try:
        stores.vault.unlock(passphrase)
    except stores.vault.VaultError as exc:
        output.fatal(str(exc))
    output.success("Encrypted Ravenstash vault unlocked.")


@storage_app.command("lock")
def credential_storage_lock() -> None:
    """Forget the encrypted vault key held by the session agent."""
    if stores.vault.lock():
        output.success("Encrypted Ravenstash vault locked.")
    else:
        output.info("Encrypted Ravenstash vault is already locked.")


@storage_app.command("change-passphrase")
def credential_storage_change_passphrase() -> None:
    """Replace the encrypted vault passphrase."""
    if not stores.vault.exists():
        output.fatal("Encrypted Ravenstash vault is not initialized.")
    if not _interactive_terminal_available():
        output.fatal("Changing the vault passphrase requires an interactive terminal.")
    old_passphrase = typer.prompt("Current Ravenstash vault passphrase", hide_input=True)
    new_passphrase = typer.prompt(
        "New Ravenstash vault passphrase (8 character minimum; 12+ recommended)",
        hide_input=True,
    )
    confirmation = typer.prompt("Confirm new vault passphrase", hide_input=True)
    if new_passphrase != confirmation:
        output.fatal("Vault passphrases do not match.")
    _warn_if_short_vault_passphrase(new_passphrase)
    try:
        stores.vault.change_passphrase(old_passphrase, new_passphrase)
    except stores.vault.VaultError as exc:
        output.fatal(str(exc))
    output.success("Encrypted Ravenstash vault passphrase changed.")


@storage_app.command("set")
def keyring_set(
    store: str = typer.Argument(
        ...,
        help="Preferred store: auto, keyring, pass, vault, or plaintext.",
    ),
) -> None:
    """Set the preferred store for future device logins."""
    normalized = store.strip().lower()
    try:
        cfg_mod.set_credential_store(normalized)
    except ValueError as exc:
        output.fatal(str(exc))
    output.success(f"Credential-store preference set to '{normalized}'.")
    if normalized == "plaintext":
        output.warn("Plaintext credentials are not encrypted; prefer vault, keyring, or pass.")
    if normalized != "auto":
        status = next(
            item for item in auth_mod.credential_store_statuses() if item.name == normalized
        )
        if not status.available:
            output.warn(f"{status.detail} {status.guidance}")


@app.command("logout")
def logout(
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help="Local profile to remove credentials from (default: selected profile).",
    ),
    all_profiles: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Remove credentials from all configured local profiles.",
    ),
) -> None:
    """Remove stored credentials without deleting local profile metadata."""
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
        None, "--profile", "-p", help="Local profile to inspect (default: selected profile)."
    ),
) -> None:
    """Show local credential state for a local profile."""
    cfg = cfg_mod.load()
    profile_name = _target_profile(profile, cfg)
    p = cfg.active_profile(profile_name)
    token = auth_mod.get_token(profile_name)
    source = auth_mod.token_source(profile_name)
    credential_store = (
        "not used (RVS_TOKEN)"
        if source == "RVS_TOKEN"
        else p.credential_store or auth_mod.selected_credential_store(profile_name) or "none"
    )

    output.kv(
        {
            "Local profile": profile_name,
            "Authenticated": "yes" if token else "no",
            "Credential source": source or "none",
            "Credential store": credential_store,
            "Credential type": auth_mod.display_credential_type(p.credential_type) or "unknown",
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
        None, "--profile", "-p", help="Local profile to inspect (default: selected profile)."
    ),
) -> None:
    """Verify and print the authenticated Ravenstash user through DevAPI."""
    cfg = cfg_mod.load()
    profile_name = _target_profile(profile, cfg)
    try:
        identity = ApiClient.from_profile(profile_name).get("/me").json()
    except ApiError as exc:
        output.fatal(f"Could not verify the current identity: {exc}")
    output.kv(
        {
            "Local profile": profile_name,
            "User": identity.get("email") or identity.get("id") or "unknown",
        },
        title="Authenticated Ravenstash user",
    )


@profile_app.command("list")
def profile_list() -> None:
    """List configured local CLI profiles."""
    cfg = cfg_mod.load()
    if not cfg.profiles:
        output.info("No profiles configured. Run `rvs auth login` first.")
        return

    active_profile = _current_profile_name(cfg)
    rows: list[list[str]] = []
    for name, p in cfg.profiles.items():
        rows.append(
            [
                name,
                cfg_mod.profile_selection_source() if name == active_profile else "",
                p.api_url,
                cfg_mod.repository_domain_summary(p.native_registries),
            ]
        )
    output.table(["Local profile", "Selection", "DevAPI URL", "Repository domain"], rows)


@profile_app.command("current")
def profile_current(
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help="Local profile to inspect (default: selected profile).",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show every resolved package repository endpoint.",
    ),
) -> None:
    """Show the selected local CLI profile and its non-secret configuration."""
    cfg = cfg_mod.load()
    profile_name = _target_profile(profile, cfg)
    _require_profile(cfg, profile_name)
    selected = cfg.profiles[profile_name]
    output.kv(
        {
            "Local profile": profile_name,
            "Selection source": (
                "command option (--profile)" if profile else cfg_mod.profile_selection_source()
            ),
            "DevAPI URL": selected.api_url,
            **_repository_status_fields(selected.native_registries, verbose=verbose),
            "Configured credential store": selected.credential_store or cfg.credential_store,
        },
        title="Current local Ravenstash profile",
    )


def _use_profile(profile: str | None) -> None:
    cfg = cfg_mod.load()
    try:
        selected_profile = profile or _select_profile_interactive(cfg)
    except KeyboardInterrupt:
        output.fatal("Profile selection cancelled.")

    _require_profile(cfg, selected_profile)
    scope = cfg_mod.profile_selection_write_scope()
    cfg_mod.set_default_profile(selected_profile)
    output.success(f"Local profile '{selected_profile}' selected for {scope}.")
    _warn_env_profile_override()


@profile_app.command("use")
def profile_use(
    profile: str | None = typer.Argument(
        None,
        help="Local profile to use. Omit to choose from an interactive list.",
    ),
) -> None:
    """Use a local CLI profile in this shell or as the persisted default."""
    _use_profile(profile)


@profile_app.command("delete")
def profile_delete(
    profile: str | None = typer.Argument(
        None,
        help="Local profile to delete (default: selected profile).",
    ),
    all_profiles: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Delete all configured local profiles.",
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
    old: str = typer.Argument(..., help="Existing local profile name."),
    new: str = typer.Argument(..., help="New local profile name."),
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
    session = cfg_mod.load_session()
    if session.profile == old:
        session.profile = new
        cfg_mod.save_session(session)
    auth_mod.delete_token(old)
    output.success(f"Profile '{old}' renamed to '{new}'.")
    output.info(
        f"Run `rvs auth login --profile {new}` to store credentials for the renamed profile."
    )
