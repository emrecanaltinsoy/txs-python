"""
All command implementations — mirrors commands.sh.

Functions here are called both from __main__.py (CLI) and from ui.py
(interactive picker callbacks), so they live in their own module to avoid
circular imports.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from txs import TXS_VERSION
from txs.config import (
    CONFIG_FILE,
    SETTINGS_FILE,
    expand_path,
    get_project_prop,
    get_txs_setting,
    invalidate_config_cache,
    parse_config,
)
from txs.git import (
    get_project_worktrees,
    get_repo_info,
    is_bare_repo,
    repo_name_from_url,
)
from txs.git import (
    wt_path as compute_wt_path,
)
from txs.log import error, info
from txs.tmux import (
    attach_or_switch,
    fetch_session_windows,
    get_active_sessions,
    get_session_windows,
    is_inside_tmux,
    open_worktree_in_session,
    session_exists,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _send_on_create(session_name: str, on_create: str) -> None:
    if not on_create:
        return
    for cmd in on_create.splitlines():
        cmd = cmd.strip()
        if not cmd:
            continue
        subprocess.run(
            ["tmux", "send-keys", "-t", f"={session_name}:", cmd, "Enter"],
            check=True,
        )


def _ensure_session(session_name: str, path: str, on_create: str) -> str:
    """
    Create a tmux session if it doesn't exist.
    Returns 'created' or 'existed'.
    """
    if session_exists(session_name):
        return "existed"
    info(f"Creating session [green]{session_name}[/green] at {path}...")
    result = subprocess.run(
        ["tmux", "new-session", "-d", "-s", session_name, "-c", path],
    )
    if result.returncode != 0:
        error(f"Failed to create tmux session '{session_name}'")
        raise SystemExit(1)
    # For bare repos, defer on_create until we cd into the worktree
    if not is_bare_repo(path):
        _send_on_create(session_name, on_create)
    return "created"


def _attach_bare_repo(
    project: str,
    path: str,
    session_name: str,
    on_create: str,
    worktree_selector: str,
    just_created: bool,
) -> None:
    """Handle worktree selection and attach for a bare repo project."""
    from txs.ui import pick_worktree  # avoid top-level circular import

    target_wt_path = ""

    if worktree_selector:
        for wt, wt_name in get_project_worktrees(path):
            if wt_name == worktree_selector:
                target_wt_path = wt
                break
        if not target_wt_path:
            error(f"Worktree '{worktree_selector}' not found in project '{project}'.")
            raise SystemExit(1)
    else:
        branch = pick_worktree(path)
        if branch is None:
            attach_or_switch(session_name)
            return
        target_wt_path = compute_wt_path(path, "bare", branch)

    if not target_wt_path:
        return

    if just_created:
        subprocess.run(
            [
                "tmux",
                "send-keys",
                "-t",
                f"={session_name}:",
                f"cd {target_wt_path}",
                "Enter",
            ],
            check=True,
        )
        subprocess.run(
            [
                "tmux",
                "rename-window",
                "-t",
                f"={session_name}:",
                os.path.basename(target_wt_path),
            ],
            check=True,
        )
        _send_on_create(session_name, on_create)
        attach_or_switch(session_name)
    else:
        open_worktree_in_session(session_name, target_wt_path, on_create)


# ---------------------------------------------------------------------------
# cmd_ls
# ---------------------------------------------------------------------------


def cmd_ls(filter_arg: str = "") -> None:
    match filter_arg:
        case "sessions":
            _ls_sessions()
        case "projects":
            _ls_projects()
        case "worktrees":
            _ls_worktrees()
        case "":
            _ls_sessions()
            print()
            _ls_projects()
            print()
            _ls_worktrees()
        case _:
            error(f"Unknown filter '{filter_arg}'. Use: sessions, projects, worktrees")
            raise SystemExit(1)


def _ls_sessions() -> None:
    from rich.console import Console

    con = Console()
    sessions = get_active_sessions()
    if not sessions:
        con.print("[dim]No active tmux sessions.[/dim]")
        return
    fetch_session_windows()
    con.print("[bold]Active sessions:[/bold]\n")
    for session in sessions:
        windows = get_session_windows(session)
        con.print(f"  [green]{session}[/green]  [dim][{windows}][/dim]")


def _ls_projects() -> None:
    from rich.console import Console

    from txs.config import build_depth_index, find_depth_owner, is_explicit_project_path

    con = Console()
    cfg = parse_config()
    build_depth_index(cfg)

    if not cfg.projects:
        con.print(f"[dim]No projects configured in {CONFIG_FILE}[/dim]")
        return

    active_sessions = get_active_sessions()
    con.print("[bold]Configured projects:[/bold]\n")

    for proj in cfg.projects:
        path = expand_path(get_project_prop(cfg, proj.name, "path"))
        depth = proj.max_depth

        if depth > 0:
            from txs.git import get_depth_projects

            con.print(f"  [cyan]{proj.name}[/cyan]  [dim][depth={depth}][/dim]  {path}")
            for dp_path, dp_name in get_depth_projects(path, depth):
                if not dp_path:
                    continue
                if is_explicit_project_path(cfg, dp_path):
                    continue
                owner = find_depth_owner(cfg, dp_name)
                if owner is None or owner[0] != proj.name:
                    continue
                status = (
                    "[green]active[/green]"
                    if dp_name in active_sessions
                    else "[dim]inactive[/dim]"
                )
                con.print(f"    {dp_name}  [{status}]  {dp_path}")
            continue

        if not os.path.isdir(path):
            continue
        session_name = get_project_prop(cfg, proj.name, "session_name")
        status = (
            "[green]active[/green]"
            if session_name in active_sessions
            else "[dim]inactive[/dim]"
        )
        con.print(f"  [cyan]{proj.name}[/cyan]  [{status}]  {path}")


def _ls_worktrees() -> None:
    from rich.console import Console

    con = Console()
    cfg = parse_config()
    found = False

    for proj in cfg.projects:
        path = expand_path(get_project_prop(cfg, proj.name, "path"))
        if not os.path.isdir(path):
            continue
        if not is_bare_repo(path):
            continue
        worktrees = sorted(get_project_worktrees(path), key=lambda x: x[1])
        for wt_path, wt_name in worktrees:
            if not wt_path:
                continue
            if not found:
                con.print("[bold]Worktrees:[/bold]\n")
                found = True
            con.print(f"  [cyan]{proj.name}[/cyan] - {wt_name}  [dim]{wt_path}[/dim]")

    if not found:
        con.print("[dim]No worktrees found.[/dim]")


# ---------------------------------------------------------------------------
# cmd_attach
# ---------------------------------------------------------------------------


def cmd_attach(project: str = "", worktree_selector: str = "") -> None:
    if not project:
        from txs.ui import cmd_interactive

        cmd_interactive()
        return

    cfg = parse_config()
    proj_obj = cfg._by_name(project)
    if proj_obj is None:
        error(f"Project '{project}' not found in config.")
        print("Available projects:")
        for p in cfg.projects:
            print(f"  - {p.name}")
        raise SystemExit(1)

    path = expand_path(get_project_prop(cfg, project, "path"))
    session_name = get_project_prop(cfg, project, "session_name")
    on_create = get_project_prop(cfg, project, "on_create")

    if not os.path.isdir(path):
        error(f"Directory does not exist: {path}")
        raise SystemExit(1)

    session_state = _ensure_session(session_name, path, on_create)
    just_created = session_state == "created"

    if is_bare_repo(path):
        _attach_bare_repo(
            project, path, session_name, on_create, worktree_selector, just_created
        )
        return

    attach_or_switch(session_name)


# ---------------------------------------------------------------------------
# cmd_kill
# ---------------------------------------------------------------------------


def _kill_window() -> None:
    from rich.console import Console

    con = Console()

    if not shutil.which("fzf"):
        error("fzf is required for interactive kill. Usage: txs kill window")
        raise SystemExit(1)

    active_sessions = get_active_sessions()
    if not active_sessions:
        con.print("[dim]No active tmux sessions.[/dim]")
        return

    # Build flat list: label \t session \t win_index
    entries: list[str] = []
    for session in active_sessions:
        result = subprocess.run(
            [
                "tmux",
                "list-windows",
                "-t",
                f"={session}",
                "-F",
                "#{window_index}|#{window_name}",
            ],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if not line:
                continue
            win_index, _, win_name = line.partition("|")
            label = f"{session} — {win_name}"
            entries.append(f"{label}\t{session}\t{win_index}")

    if not entries:
        con.print("[dim]No open windows found.[/dim]")
        return

    result = subprocess.run(
        [
            "fzf",
            "--delimiter=\t",
            "--with-nth=1",
            "--header=Pick a window to kill (ESC to cancel)",
            "--prompt=kill window> ",
            f"--height={get_txs_setting('fzf_height') or '50%'}",
            "--layout=reverse",
            "--border",
            "--ansi",
        ],
        input="\n".join(entries),
        text=True,
        stdout=subprocess.PIPE,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return

    sel_label, _, rest = result.stdout.strip().partition("\t")
    sel_session, _, sel_win_index = rest.partition("\t")

    if is_inside_tmux():
        cur_session = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_name}"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        cur_win = subprocess.run(
            ["tmux", "display-message", "-p", "#{window_index}"],
            capture_output=True,
            text=True,
        ).stdout.strip()

        if sel_session == cur_session and sel_win_index == cur_win:
            win_count = int(
                subprocess.run(
                    ["tmux", "list-windows", "-t", f"={sel_session}"],
                    capture_output=True,
                    text=True,
                ).stdout.count("\n")
            )
            if win_count <= 1:
                subprocess.run(["tmux", "switch-client", "-l"])
            else:
                subprocess.run(["tmux", "last-window", "-t", f"={sel_session}"])

    subprocess.run(
        ["tmux", "kill-window", "-t", f"={sel_session}:{sel_win_index}"], check=True
    )
    from rich.console import Console

    Console().print(f"Killed window [green]{sel_label}[/green].")


def cmd_kill(target: str = "") -> None:
    from rich.console import Console

    con = Console()

    if target == "window":
        _kill_window()
        return

    if not target:
        if not shutil.which("fzf"):
            error(
                "fzf is required for interactive kill. Usage: txs kill <session-name>"
            )
            raise SystemExit(1)
        sessions = get_active_sessions()
        if not sessions:
            con.print("[dim]No active tmux sessions.[/dim]")
            return
        result = subprocess.run(
            [
                "fzf",
                "--header=Pick a session to kill (ESC to cancel)",
                "--prompt=kill> ",
                f"--height={get_txs_setting('fzf_height') or '50%'}",
                "--layout=reverse",
                "--border",
                "--ansi",
            ],
            input="\n".join(sessions),
            text=True,
            stdout=subprocess.PIPE,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return
        target = result.stdout.strip()

    if not session_exists(target):
        error(f"Session '{target}' does not exist.")
        raise SystemExit(1)

    if is_inside_tmux():
        cur = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_name}"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if cur == target:
            if subprocess.run(["tmux", "switch-client", "-l"]).returncode != 0:
                remaining = [s for s in get_active_sessions() if s != target]
                if remaining:
                    subprocess.run(["tmux", "switch-client", "-t", f"={remaining[0]}"])

    subprocess.run(["tmux", "kill-session", "-t", f"={target}"], check=True)
    con.print(f"Killed session [green]{target}[/green].")


# ---------------------------------------------------------------------------
# cmd_add / cmd_remove
# ---------------------------------------------------------------------------

_SECTION_NAME_RE = re.compile(r"^[a-zA-Z0-9_.−-]+$")


def cmd_add(raw_path: str = ".") -> None:
    if not os.path.exists(raw_path):
        error(f"Directory does not exist: {raw_path}")
        raise SystemExit(1)

    try:
        resolved = str(Path(raw_path).resolve())
    except OSError:
        error(f"Could not resolve path: {raw_path}")
        raise SystemExit(1)

    if not os.path.isdir(resolved):
        error(f"Directory does not exist: {resolved}")
        raise SystemExit(1)

    name = os.path.basename(resolved)
    # Sanitise: only keep characters valid in INI section names
    name = re.sub(r"[^a-zA-Z0-9_.\-]", "-", name)
    if not name:
        error("Could not derive a project name from path.")
        raise SystemExit(1)

    # Check for duplicate section
    if CONFIG_FILE.exists():
        content = CONFIG_FILE.read_text()
        if re.search(rf"^\[{re.escape(name)}\]\s*$", content, re.MULTILINE):
            error(f"Project '{name}' already exists in {CONFIG_FILE}")
            raise SystemExit(1)

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("a") as f:
        f.write(f"\n[{name}]\npath = {resolved}\n")

    invalidate_config_cache()
    info(f"Added project [green]{name}[/green] ({resolved})")


def cmd_remove(project: str) -> None:
    if not CONFIG_FILE.exists():
        error(f"Config file not found: {CONFIG_FILE}")
        raise SystemExit(1)

    content = CONFIG_FILE.read_text()
    if not re.search(rf"^\[{re.escape(project)}\]\s*$", content, re.MULTILINE):
        error(f"Project '{project}' not found in {CONFIG_FILE}")
        raise SystemExit(1)

    # Remove section header + all following key/continuation lines until next section or EOF
    lines = content.splitlines()
    result_lines: list[str] = []
    skip = False
    for line in lines:
        stripped = line.rstrip()
        if re.match(r"^\[", stripped):
            if stripped == f"[{project}]":
                skip = True
                continue
            else:
                skip = False
        if skip:
            continue
        result_lines.append(line)

    # Remove trailing blank lines
    while result_lines and not result_lines[-1].strip():
        result_lines.pop()

    CONFIG_FILE.write_text("\n".join(result_lines) + ("\n" if result_lines else ""))
    invalidate_config_cache()
    info(f"Removed project [green]{project}[/green]")


# ---------------------------------------------------------------------------
# cmd_config
# ---------------------------------------------------------------------------


def cmd_config(target: str = "") -> None:
    match target:
        case "settings":
            file = SETTINGS_FILE
        case "projects" | "":
            file = CONFIG_FILE
        case _:
            error(f"Unknown config target '{target}'. Use: projects, settings")
            raise SystemExit(1)

    editor = os.environ.get("EDITOR", "vi")
    if not file.exists():
        file.parent.mkdir(parents=True, exist_ok=True)
        file.touch()
    os.execvp(editor, [editor, str(file)])


# ---------------------------------------------------------------------------
# cmd_update
# ---------------------------------------------------------------------------


def cmd_update() -> None:
    repo_url = "git+https://github.com/emrecanaltinsoy/txs-python"

    if not shutil.which("uv"):
        error("'uv' is required to update txs.")
        raise SystemExit(1)

    info(f"Updating txs (current: {TXS_VERSION})...")
    proc = subprocess.run(["uv", "tool", "install", "--reinstall", repo_url])
    if proc.returncode != 0:
        error("txs update failed.")
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# cmd_wt  (worktree management — operates on current directory's git repo)
# ---------------------------------------------------------------------------


def _wt_add(branch: str = "") -> None:
    root, repo_type = get_repo_info()

    if not branch:
        if not sys.stdin.isatty():
            error("Missing branch name.")
            print("Usage: txs wt add <branch>", file=sys.stderr)
            raise SystemExit(1)
        branch = input("Branch name: ").strip()
        if not branch:
            error("Missing branch name.")
            raise SystemExit(1)

    result = subprocess.run(
        ["git", "check-ref-format", "--branch", branch],
        capture_output=True,
    )
    if result.returncode != 0:
        error(f"Invalid branch name: {branch}")
        raise SystemExit(1)

    dest = compute_wt_path(root, repo_type, branch)
    if os.path.isdir(dest):
        error(f"Worktree path already exists: {dest}")
        raise SystemExit(1)

    info("Fetching from origin...")
    subprocess.run(
        ["git", "-C", root, "fetch", "origin"], capture_output=True
    )  # non-fatal

    has_remote = (
        subprocess.run(
            [
                "git",
                "-C",
                root,
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/remotes/origin/{branch}",
            ],
            capture_output=True,
        ).returncode
        == 0
    )

    has_local = (
        subprocess.run(
            [
                "git",
                "-C",
                root,
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{branch}",
            ],
            capture_output=True,
        ).returncode
        == 0
    )

    if has_remote:
        if has_local:
            subprocess.run(
                ["git", "-C", root, "worktree", "add", dest, branch], check=True
            )
        else:
            subprocess.run(
                [
                    "git",
                    "-C",
                    root,
                    "worktree",
                    "add",
                    "-b",
                    branch,
                    dest,
                    f"origin/{branch}",
                ],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    root,
                    "branch",
                    "--set-upstream-to",
                    f"origin/{branch}",
                    branch,
                ],
                check=True,
            )
    else:
        subprocess.run(
            ["git", "-C", root, "worktree", "add", "-b", branch, dest], check=True
        )

    info(f"Created worktree [green]{branch}[/green] at {dest}")


def _wt_remove(branch: str = "", keep_branch: bool = False) -> None:
    root, repo_type = get_repo_info()

    if not branch:
        if not sys.stdin.isatty():
            error("Missing branch name.")
            print("Usage: txs wt remove [--keep-branch] <branch>", file=sys.stderr)
            raise SystemExit(1)
        from txs.ui import pick_worktree

        picked = pick_worktree(root, repo_type)
        if not picked:
            raise SystemExit(1)
        branch = picked

    dest = compute_wt_path(root, repo_type, branch)
    if not os.path.isdir(dest):
        error(f"Worktree '{branch}' not found at {dest}")
        raise SystemExit(1)

    result = subprocess.run(["git", "-C", root, "worktree", "remove", dest])
    if result.returncode != 0:
        error(f"Failed to remove worktree '{branch}'. It may have uncommitted changes.")
        raise SystemExit(1)
    info(f"Removed worktree [green]{branch}[/green]")

    if keep_branch:
        return

    if sys.stdin.isatty():
        ans = input(f"Keep branch '{branch}'? (y/N) ").strip()
        if ans.lower().startswith("y"):
            return

    if (
        subprocess.run(
            ["git", "-C", root, "branch", "-D", branch], capture_output=True
        ).returncode
        == 0
    ):
        info(f"Deleted branch [green]{branch}[/green]")


def _wt_list() -> None:
    from rich.console import Console

    con = Console()
    root, _ = get_repo_info()

    worktrees = sorted(get_project_worktrees(root), key=lambda x: x[1])
    if not worktrees:
        con.print("[dim]No worktrees found.[/dim]")
        return

    repo_name = os.path.basename(root)
    con.print(f"[bold]Worktrees for [cyan]{repo_name}[/cyan]:[/bold]\n")
    for wt, name in worktrees:
        con.print(f"  {name}  [dim]{wt}[/dim]")


def cmd_wt(subcmd: str = "", branch: str = "", keep_branch: bool = False) -> None:
    match subcmd:
        case "add":
            _wt_add(branch)
        case "remove":
            _wt_remove(branch, keep_branch)
        case "list" | "":
            _wt_list()
        case _:
            error(f"Unknown wt subcommand '{subcmd}'.")
            print("Usage: txs wt [add|remove|list]", file=sys.stderr)
            raise SystemExit(1)


# ---------------------------------------------------------------------------
# cmd_clone_bare
# ---------------------------------------------------------------------------


def cmd_clone_bare(repo_url: str, folder_name: str = "") -> None:
    if not folder_name:
        folder_name = repo_name_from_url(repo_url)
    if not folder_name:
        error(f"Could not derive destination folder from URL: {repo_url}")
        raise SystemExit(1)

    if os.path.exists(folder_name):
        error(f"Destination already exists: {folder_name}")
        raise SystemExit(1)

    os.makedirs(folder_name)
    cwd = os.path.join(os.getcwd(), folder_name)

    info("Cloning bare repository...")
    subprocess.run(["git", "clone", "--bare", repo_url, ".bare"], cwd=cwd, check=True)
    Path(os.path.join(cwd, ".git")).write_text("gitdir: ./.bare\n")

    info("Configuring remote tracking...")
    subprocess.run(
        ["git", "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"],
        cwd=cwd,
        check=True,
    )
    subprocess.run(["git", "fetch", "origin"], cwd=cwd, check=True)

    info("Detecting default branch...")
    default_branch = _detect_default_branch(cwd)
    if not default_branch:
        error("Could not detect a default remote branch from origin.")
        raise SystemExit(1)

    info(f"Creating worktree for [green]{default_branch}[/green]...")
    wt_dest = os.path.join(cwd, f"{folder_name}.{default_branch}")
    has_local = (
        subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{default_branch}"],
            cwd=cwd,
            capture_output=True,
        ).returncode
        == 0
    )

    if has_local:
        subprocess.run(
            ["git", "worktree", "add", wt_dest, default_branch],
            cwd=cwd,
            check=True,
        )
    else:
        subprocess.run(
            [
                "git",
                "worktree",
                "add",
                "-b",
                default_branch,
                wt_dest,
                f"origin/{default_branch}",
            ],
            cwd=cwd,
            check=True,
        )

    subprocess.run(
        [
            "git",
            "branch",
            "--set-upstream-to",
            f"origin/{default_branch}",
            default_branch,
        ],
        cwd=cwd,
        check=True,
    )
    subprocess.run(["git", "worktree", "lock", wt_dest], cwd=cwd, check=True)

    print("---------------------------------------------------")
    info(f"Success! Setup complete in: {folder_name}")
    print("Your repo data is hidden in .bare/")
    print(f"Your active worktree is in ./{default_branch}")

    auto_add = get_txs_setting("auto_add_clone")
    if auto_add == "true":
        cmd_add(folder_name)


def _detect_default_branch(cwd: str) -> str:
    res = subprocess.run(
        ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout.strip().removeprefix("origin/")

    for branch in ("main", "master"):
        res = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}"],
            cwd=cwd,
            capture_output=True,
        )
        if res.returncode == 0:
            return branch

    res = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    for line in res.stdout.splitlines():
        name = line.removeprefix("origin/")
        if name and name != "HEAD":
            return name

    return ""
