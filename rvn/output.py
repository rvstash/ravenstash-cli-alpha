"""Rich-based terminal output helpers for rvn."""

from __future__ import annotations

from typing import NoReturn

from rich.console import Console
from rich.table import Table
from rich.text import Text


console = Console()
err_console = Console(stderr=True)


def success(msg: str) -> None:
    console.print(f"[bold green]✓[/] {msg}")


def info(msg: str) -> None:
    console.print(f"[cyan]→[/] {msg}")


def warn(msg: str) -> None:
    err_console.print(f"[bold yellow]![/] {msg}")


def error(msg: str) -> None:
    err_console.print(f"[bold red]✗[/] {msg}")


def fatal(msg: str) -> NoReturn:
    err_console.print(f"[bold red]Error:[/] {msg}")
    raise SystemExit(1)


def table(columns: list[str], rows: list[list[str]], title: str | None = None) -> None:
    t = Table(title=title, show_header=True, header_style="bold dim")
    for col in columns:
        t.add_column(col)
    for row in rows:
        t.add_row(*row)
    console.print(t)


def section(title: str) -> None:
    console.print(f"\n[bold]{title}[/]")


def kv(pairs: dict[str, str | None], title: str | None = None) -> None:
    t = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    t.add_column("key", style="bold dim", no_wrap=True)
    t.add_column("value")
    for k, v in pairs.items():
        t.add_row(k, v or Text("—", style="dim"))
    if title:
        console.print(f"[bold]{title}[/]")
    console.print(t)
