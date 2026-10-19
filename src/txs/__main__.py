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
        _run_tui()


def _run_tui() -> None:
    import os
    from txs.commands import _attach_bare_repo, _ensure_session, cmd_attach, cmd_kill
    from txs.config import expand_path, get_project_prop, parse_config
    from txs.git import depth_session_name, is_bare_repo
    from txs.tmux import (
        attach_or_switch,
        open_worktree_in_session,
        sanitize_session_name,
    )
    from txs.tui.app import TxsApp

    result = TxsApp().run()

    if not result:
        return

    action, *args = result

    match action:
        case "attach_session":
            session, wt_path = args
            if wt_path:
                open_worktree_in_session(session, wt_path)
            else:
                attach_or_switch(session)

        case "attach_project":
            project, path, wt_path, session_name = args
            # Check if this is a depth-discovered repo (path != the project's own root)
            try:
                cfg = parse_config()
                proj_root = expand_path(get_project_prop(cfg, project, "path"))
            except SystemExit:
                proj_root = ""

            if path and path != proj_root:
                # Depth-discovered repo — session is the repo itself, not the parent group
                on_create = get_project_prop(cfg, project, "on_create") if cfg else ""
                sname = sanitize_session_name(
                    depth_session_name(wt_path if wt_path else path)
                )
                if wt_path:
                    parent = os.path.dirname(wt_path)
                    if is_bare_repo(parent):
                        created = _ensure_session(sname, parent, on_create) == "created"
                        _attach_bare_repo(
                            project,
                            parent,
                            sname,
                            on_create,
                            os.path.basename(wt_path),
                            created,
                        )
                    else:
                        _ensure_session(sname, wt_path, on_create)
                        attach_or_switch(sname)
                else:
                    _ensure_session(sname, path, on_create)
                    attach_or_switch(sname)
            else:
                # Direct project
                cmd_attach(project, wt_path or "")

        case "kill_session":
            cmd_kill(args[0])


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
