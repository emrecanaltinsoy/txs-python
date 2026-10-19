"""Logging helpers — mirrors log.sh info/warn/error."""

from rich.console import Console

# stdout for info, stderr for warn/error (matches bash behaviour)
_out = Console()
_err = Console(stderr=True)


def info(msg: str) -> None:
    _out.print(f"[green]>[/green] {msg}")


def warn(msg: str) -> None:
    _err.print(f"[yellow]Warning:[/yellow] {msg}")


def error(msg: str) -> None:
    _err.print(f"[red]Error:[/red] {msg}")
