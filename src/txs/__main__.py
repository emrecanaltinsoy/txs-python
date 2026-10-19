"""
txs CLI entry point — mirrors bin/txs.

Registered as 'txs' in pyproject.toml.
"""

from __future__ import annotations

from typing import Annotated

import typer

from txs import TXS_VERSION

app = typer.Typer(
    name="txs",
    help="Manage tmux sessions from predefined project directories.",
    add_completion=True,
    no_args_is_help=False,
    invoke_without_command=True,
)

# Worktree subcommand group
wt_app = typer.Typer(help="Worktree management (run from any git repo).")
app.add_typer(wt_app, name="wt")


# ---------------------------------------------------------------------------
# Root callback — no subcommand → interactive picker
# ---------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", "-v", is_eager=True, help="Show version and exit."),
    ] = False,
) -> None:
    if version:
        typer.echo(f"txs {TXS_VERSION}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        from txs.ui import cmd_interactive

        cmd_interactive()


# ---------------------------------------------------------------------------
# txs attach
# ---------------------------------------------------------------------------


@app.command()
def attach(
    project: Annotated[str, typer.Argument(help="Project name.")] = "",
    worktree: Annotated[str, typer.Argument(help="Worktree branch name.")] = "",
) -> None:
    """Attach to a session, or open a worktree window."""
    _require_tmux()
    from txs.commands import cmd_attach

    cmd_attach(project, worktree)


# ---------------------------------------------------------------------------
# txs switch
# ---------------------------------------------------------------------------


@app.command()
def switch() -> None:
    """Pick from open sessions/windows only."""
    _require_tmux()
    from txs.ui import cmd_switch

    cmd_switch()


# ---------------------------------------------------------------------------
# txs kill
# ---------------------------------------------------------------------------


@app.command()
def kill(
    target: Annotated[
        str,
        typer.Argument(help="Session name, or 'window' to kill a specific window."),
    ] = "",
) -> None:
    """Kill a session (interactive picker when no arg), or kill a specific window."""
    _require_tmux()
    from txs.commands import cmd_kill

    cmd_kill(target)


# ---------------------------------------------------------------------------
# txs ls / list / sessions / projects
# ---------------------------------------------------------------------------


@app.command(name="ls")
def ls(
    filter_arg: Annotated[
        str,
        typer.Argument(help="Filter: sessions, projects, or worktrees."),
    ] = "",
) -> None:
    """List sessions, projects, and/or worktrees."""
    _require_tmux()
    from txs.commands import cmd_ls

    cmd_ls(filter_arg)


@app.command(name="list", hidden=True)
def list_alias(
    filter_arg: Annotated[str, typer.Argument()] = "",
) -> None:
    """Alias for 'ls'."""
    _require_tmux()
    from txs.commands import cmd_ls

    cmd_ls(filter_arg)


@app.command(name="sessions", hidden=True)
def sessions_alias() -> None:
    """Alias for 'ls sessions'."""
    _require_tmux()
    from txs.commands import cmd_ls

    cmd_ls("sessions")


@app.command(name="projects", hidden=True)
def projects_alias() -> None:
    """Alias for 'ls projects'."""
    _require_tmux()
    from txs.commands import cmd_ls

    cmd_ls("projects")


# ---------------------------------------------------------------------------
# txs wt add / remove / list
# ---------------------------------------------------------------------------


@wt_app.callback(invoke_without_command=True)
def _wt_root(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from txs.commands import _wt_list

        _wt_list()


@wt_app.command(name="add")
def wt_add(
    branch: Annotated[str, typer.Argument(help="Branch name.")] = "",
) -> None:
    """Create a worktree (prompts if branch omitted)."""
    from txs.commands import _wt_add

    _wt_add(branch)


@wt_app.command(name="remove")
def wt_remove(
    branch: Annotated[str, typer.Argument(help="Branch name.")] = "",
    keep_branch: Annotated[
        bool,
        typer.Option(
            "--keep-branch", "-k", help="Keep the git branch after removing worktree."
        ),
    ] = False,
) -> None:
    """Remove a worktree (picker if branch omitted)."""
    from txs.commands import _wt_remove

    _wt_remove(branch, keep_branch)


@wt_app.command(name="list")
def wt_list() -> None:
    """List worktrees for the current repo."""
    from txs.commands import _wt_list

    _wt_list()


# ---------------------------------------------------------------------------
# txs add / remove
# ---------------------------------------------------------------------------


@app.command(name="add")
def add(
    path: Annotated[str, typer.Argument(help="Directory to add (default: .).")] = ".",
) -> None:
    """Add a directory to the project config."""
    from txs.commands import cmd_add

    cmd_add(path)


@app.command(name="remove")
def remove(
    project: Annotated[str, typer.Argument(help="Project name to remove.")],
) -> None:
    """Remove a project from the config."""
    from txs.commands import cmd_remove

    cmd_remove(project)


# ---------------------------------------------------------------------------
# txs clone-bare
# ---------------------------------------------------------------------------


@app.command(name="clone-bare")
def clone_bare(
    url: Annotated[str, typer.Argument(help="Repository URL.")],
    name: Annotated[str, typer.Argument(help="Destination folder name.")] = "",
) -> None:
    """Clone a repo as bare + create default worktree."""
    _require_tmux(optional=True)
    from txs.commands import cmd_clone_bare

    cmd_clone_bare(url, name)


# ---------------------------------------------------------------------------
# txs config
# ---------------------------------------------------------------------------


@app.command(name="config")
def config(
    target: Annotated[
        str,
        typer.Argument(help="'projects' (default) or 'settings'."),
    ] = "",
) -> None:
    """Open a config file in $EDITOR."""
    from txs.commands import cmd_config

    cmd_config(target)


# ---------------------------------------------------------------------------
# txs update
# ---------------------------------------------------------------------------


@app.command(name="update")
def update() -> None:
    """Update txs to the latest version."""
    from txs.commands import cmd_update

    cmd_update()


# ---------------------------------------------------------------------------
# txs version
# ---------------------------------------------------------------------------


@app.command(name="version")
def version() -> None:
    """Show version."""
    typer.echo(f"txs {TXS_VERSION}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_tmux(optional: bool = False) -> None:
    import shutil

    if shutil.which("tmux") is None and not optional:
        from txs.log import error

        error("tmux is required but not installed.")
        raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
