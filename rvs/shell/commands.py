"""Fast local-only shell prompt integration."""

from __future__ import annotations

import os
from pathlib import Path

import typer

from .. import config as cfg_mod
from .. import output
from ..account.commands import display_name
from ..paths import rvs_home


app = typer.Typer(
    name="shell",
    help="Install and inspect shell-local Ravenstash context integration.",
    no_args_is_help=True,
)


def prompt_text() -> str:
    cfg = cfg_mod.load()
    profile_name = cfg_mod.current_profile_name(cfg)
    customer_id = cfg_mod.current_customer_id(profile_name, cfg)
    account = cfg_mod.cached_account(profile_name, customer_id)
    if account is not None:
        account_name = display_name(account)
        target = account.selected_target
    else:
        profile = cfg.profiles.get(profile_name)
        account_name = "personal" if profile is not None and profile.customer_id else "no-account"
        target = None
    parts = [profile_name, account_name]
    if target is not None:
        parts.append(target.display_selector)
    return f"({' · '.join(parts)}) "


@app.command("prompt", hidden=True)
def prompt() -> None:
    """Print the prompt fragment using local state only."""
    typer.echo(prompt_text(), nl=False)


def _posix_snippet() -> str:
    return """# rvs shell context
if [ -z "${RVS_SESSION_ID:-}" ]; then
  export RVS_SESSION_ID="rvs-$$-${RANDOM:-0}"
fi
if [ -z "${RVS_PROMPT_INSTALLED:-}" ]; then
  export RVS_PROMPT_INSTALLED=1
  if [ -n "${ZSH_VERSION:-}" ]; then
    setopt PROMPT_SUBST
  fi
  RVS_ORIGINAL_PS1="$PS1"
  __rvs_prompt_context() { command rvs shell prompt 2>/dev/null; }
  PS1='$(__rvs_prompt_context)'"$RVS_ORIGINAL_PS1"
fi
"""


def _fish_snippet() -> str:
    return """# rvs shell context
if not set -q RVS_SESSION_ID
    set -gx RVS_SESSION_ID "rvs-$fish_pid-"(random)
end
if not set -q RVS_PROMPT_INSTALLED
    set -gx RVS_PROMPT_INSTALLED 1
    functions -c fish_prompt __rvs_original_fish_prompt
    function fish_prompt
        command rvs shell prompt 2>/dev/null
        __rvs_original_fish_prompt
    end
end
"""


def _append_source(rc_path: Path, source_line: str) -> bool:
    content = rc_path.read_text(encoding="utf-8") if rc_path.exists() else ""
    if source_line in content:
        return False
    rc_path.parent.mkdir(parents=True, exist_ok=True)
    with rc_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n# Ravenstash account and package-target prompt\n{source_line}\n")
    return True


@app.command("setup")
def setup(
    shell: str | None = typer.Option(
        None,
        "--shell",
        help="Shell: bash, zsh, or fish. Auto-detected from $SHELL.",
    ),
) -> None:
    """Install the session-aware Ravenstash prompt hook."""
    selected_shell = shell or Path(os.environ.get("SHELL", "")).name
    if selected_shell not in {"bash", "zsh", "fish"}:
        output.fatal("Cannot detect a supported shell. Pass --shell bash, zsh, or fish.")
    home = rvs_home()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    home.chmod(0o700)
    if selected_shell == "fish":
        integration = home / "shell.fish"
        integration.write_text(_fish_snippet(), encoding="utf-8")
        integration.chmod(0o600)
        rc_path = Path.home() / ".config" / "fish" / "conf.d" / "rvs-context.fish"
        source_line = f'source "{integration}"'
    else:
        integration = home / "shell.sh"
        integration.write_text(_posix_snippet(), encoding="utf-8")
        integration.chmod(0o600)
        rc_path = Path.home() / (".zshrc" if selected_shell == "zsh" else ".bashrc")
        source_line = f'. "{integration}"'
    changed = _append_source(rc_path, source_line)
    if changed:
        output.success(f"Installed Ravenstash context prompt for {selected_shell} in {rc_path}.")
    else:
        output.info(f"Ravenstash context prompt is already configured in {rc_path}.")
    output.info(f"Restart the shell or run: {source_line}")
