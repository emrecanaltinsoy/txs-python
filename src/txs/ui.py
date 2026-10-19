"""
Interactive pickers and session-picker command — mirrors ui.sh.

cmd_interactive()  →  txs (no args)
cmd_switch()       →  txs switch
pick_worktree()    →  reusable fzf worktree picker
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from txs.config import (
    ProjectConfig,
    build_depth_index,
    expand_path,
    find_depth_owner,
    find_project_for_session,
    get_project_prop,
    get_txs_setting,
    is_explicit_project_path,
    parse_config,
)
from txs.git import (
    depth_session_name,
    get_depth_projects,
    get_project_worktrees,
    is_bare_repo,
)
from txs.log import error
from txs.tmux import (
    attach_or_switch,
    fetch_session_windows,
    find_window_by_path,
    get_active_sessions,
    get_session_windows,
    open_worktree_in_session,
    sanitize_session_name,
)


def _fzf_height() -> str:
    return get_txs_setting("fzf_height") or "50%"


def _require_fzf() -> bool:
    if shutil.which("fzf") is None:
        error("fzf is required for interactive mode.")
        return False
    return True


# ---------------------------------------------------------------------------
# Entry dataclass for the picker
# ---------------------------------------------------------------------------


@dataclass
class PickerEntry:
    marker: str  # '*', ' ', '+'
    session: str  # '-' when no active session
    project: str  # '-' when no project
    wt_path: str  # '-' when no worktree path
    name: str  # display name
    state: str  # display state (windows, [active], etc.)

    def to_row(self) -> str:
        return f"{self.marker}\t{self.session}\t{self.project}\t{self.wt_path}\t{self.name}\t{self.state}"

    @staticmethod
    def from_row(row: str) -> PickerEntry:
        parts = row.split("\t")
        # fzf output has 6 original fields; the display field (5th) may be padded
        marker, session, project, wt, *_rest = parts
        # The 5th column is the padded display name + state; we don't need to
        # re-parse it — we only need the first 4 fields to take action.
        return PickerEntry(
            marker=marker,
            session="" if session == "-" else session,
            project="" if project == "-" else project,
            wt_path="" if wt == "-" else wt,
            name="",
            state="",
        )


def _picker_format(entries: list[PickerEntry]) -> str:
    """
    Mirrors _picker_format() awk script in ui.sh.
    Pads the name field so the state column lines up.
    Returns the formatted lines as a single string ready for fzf stdin.
    """
    if not entries:
        return ""
    max_len = max(len(e.name) for e in entries)
    lines = []
    for e in entries:
        padded_name = f"{e.marker} {e.name:<{max_len}}  {e.state}"
        row = f"{e.marker}\t{e.session}\t{e.project}\t{e.wt_path}\t{padded_name}\t{e.state}"
        lines.append(row)
    return "\n".join(lines)


def _run_fzf(input_str: str, header: str, prompt: str) -> str | None:
    """Run fzf with standard options; return selected line or None if cancelled."""
    result = subprocess.run(
        [
            "fzf",
            "--delimiter=\t",
            "--with-nth=5",
            f"--header={header}",
            f"--prompt={prompt}",
            f"--height={_fzf_height()}",
            "--layout=reverse",
            "--border",
            "--ansi",
        ],
        input=input_str,
        text=True,
        capture_output=False,
        stdout=subprocess.PIPE,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


# ---------------------------------------------------------------------------
# Worktree picker
# ---------------------------------------------------------------------------


def pick_worktree(repo_root: str, repo_type: str = "bare") -> str | None:
    """
    Interactive worktree picker for a repo.
    Returns the branch name (stripped of <reponame>. prefix), or None.
    """
    if not _require_fzf():
        return None

    repo_name = os.path.basename(repo_root)
    worktrees = sorted(get_project_worktrees(repo_root), key=lambda x: x[1])

    if repo_type == "normal":
        # Filter out the main worktree (path == repo_root)
        import pathlib

        filtered = []
        for wt, name in worktrees:
            try:
                resolved = str(pathlib.Path(wt).resolve())
            except OSError:
                continue
            if resolved == repo_root:
                continue
            filtered.append((wt, name))
        worktrees = filtered

    if not worktrees:
        error("No worktrees found.")
        return None

    fzf_input = "\n".join(f"{wt}\t{name}" for wt, name in worktrees)
    result = subprocess.run(
        [
            "fzf",
            "--delimiter=\t",
            "--with-nth=2",
            "--header=Pick a worktree (ESC to cancel)",
            "--prompt=worktree> ",
            f"--height={_fzf_height()}",
            "--layout=reverse",
            "--border",
            "--ansi",
        ],
        input=fzf_input,
        text=True,
        stdout=subprocess.PIPE,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None

    _, _, wt_name = result.stdout.strip().partition("\t")
    # Strip <reponame>. prefix
    prefix = f"{repo_name}."
    if wt_name.startswith(prefix):
        return wt_name[len(prefix) :]
    return wt_name


# ---------------------------------------------------------------------------
# Helpers shared between cmd_interactive and cmd_switch
# ---------------------------------------------------------------------------


def _depth_project_tag(root: str, dp_path: str) -> str:
    """
    Returns the relative parent path from root to dp_path, e.g.:
      root=~/Projects  dp_path=~/Projects/proj1          -> Projects
      root=~/Projects  dp_path=~/Projects/PROJ2/api       -> PROJ2
    """
    relative = (
        dp_path[len(root) + 1 :] if dp_path.startswith(root + os.sep) else dp_path
    )
    parent = os.path.dirname(relative)
    if not parent or parent == ".":
        return os.path.basename(root)
    return parent


def _collect_active_session_entries(
    cfg: ProjectConfig,
    active_sessions: list[str],
    seen_projects: set[str],
    seen_depth_sessions: set[str],
    switch_mode: bool = False,
) -> list[PickerEntry]:
    """Build picker entries for all active sessions."""
    entries: list[PickerEntry] = []

    for session in active_sessions:
        proj = find_project_for_session(cfg, session)
        depth_info = find_depth_owner(cfg, session)

        # Depth-discovered active session
        if proj is None and depth_info is not None:
            depth_proj, dp_path = depth_info
            seen_depth_sessions.add(session)
            tag_root = expand_path(get_project_prop(cfg, depth_proj, "path"))
            tag = _depth_project_tag(tag_root, dp_path)

            if dp_path and os.path.isdir(dp_path) and is_bare_repo(dp_path):
                for wt, wt_name in sorted(
                    get_project_worktrees(dp_path), key=lambda x: x[1]
                ):
                    matched = find_window_by_path(session, wt)
                    if switch_mode and matched is None:
                        continue
                    marker = "*" if matched else " "
                    state = "[active]" if matched else "[no window]"
                    entries.append(
                        PickerEntry(
                            marker=marker,
                            session=session,
                            project=depth_proj,
                            wt_path=wt,
                            name=f"[{tag}] {session} - {wt_name}",
                            state=state,
                        )
                    )
            else:
                windows = get_session_windows(session)
                entries.append(
                    PickerEntry(
                        marker="*",
                        session=session,
                        project=depth_proj,
                        wt_path="-",
                        name=f"[{tag}] {session}",
                        state=f"[{windows}]",
                    )
                )
            continue

        display_name = proj or session

        if proj:
            seen_projects.add(proj)
            path = expand_path(get_project_prop(cfg, proj, "path"))

            if os.path.isdir(path) and is_bare_repo(path):
                for wt, wt_name in sorted(
                    get_project_worktrees(path), key=lambda x: x[1]
                ):
                    matched = find_window_by_path(session, wt)
                    if switch_mode and matched is None:
                        continue
                    marker = "*" if matched else " "
                    state = "[active]" if matched else "[no window]"
                    entries.append(
                        PickerEntry(
                            marker=marker,
                            session=session,
                            project=proj,
                            wt_path=wt,
                            name=f"{display_name} - {wt_name}",
                            state=state,
                        )
                    )
                continue

        windows = get_session_windows(session)
        entries.append(
            PickerEntry(
                marker="*",
                session=session,
                project=proj or "-",
                wt_path="-",
                name=display_name,
                state=f"[{windows}]",
            )
        )

    return entries


def _collect_inactive_project_entries(
    cfg: ProjectConfig,
    seen_projects: set[str],
    seen_depth_sessions: set[str],
) -> list[PickerEntry]:
    """Build picker entries for inactive projects."""
    entries: list[PickerEntry] = []

    for proj in cfg.projects:
        depth = proj.max_depth
        path = expand_path(get_project_prop(cfg, proj.name, "path"))

        if depth > 0:
            for dp_path, dp_name in get_depth_projects(path, depth):
                if dp_name in seen_depth_sessions:
                    continue
                if is_explicit_project_path(cfg, dp_path):
                    continue
                owner_info = find_depth_owner(cfg, dp_name)
                if owner_info is None or owner_info[0] != proj.name:
                    continue
                tag = _depth_project_tag(path, dp_path)

                if os.path.isdir(dp_path) and is_bare_repo(dp_path):
                    for wt, wt_name in sorted(
                        get_project_worktrees(dp_path), key=lambda x: x[1]
                    ):
                        entries.append(
                            PickerEntry(
                                marker="+",
                                session="-",
                                project=proj.name,
                                wt_path=wt,
                                name=f"[{tag}] {dp_name} - {wt_name}",
                                state="",
                            )
                        )
                else:
                    entries.append(
                        PickerEntry(
                            marker="+",
                            session="-",
                            project=proj.name,
                            wt_path=dp_path,
                            name=f"[{tag}] {dp_name}",
                            state="",
                        )
                    )
            continue

        if proj.name in seen_projects:
            continue
        if not os.path.isdir(path):
            continue

        if is_bare_repo(path):
            for wt, wt_name in sorted(get_project_worktrees(path), key=lambda x: x[1]):
                entries.append(
                    PickerEntry(
                        marker="+",
                        session="-",
                        project=proj.name,
                        wt_path=wt,
                        name=f"{proj.name} - {wt_name}",
                        state="",
                    )
                )
        else:
            entries.append(
                PickerEntry(
                    marker="+",
                    session="-",
                    project=proj.name,
                    wt_path="-",
                    name=proj.name,
                    state="",
                )
            )

    return entries


# ---------------------------------------------------------------------------
# cmd_interactive
# ---------------------------------------------------------------------------


def cmd_interactive() -> None:
    if not _require_fzf():
        raise SystemExit(1)

    cfg = parse_config()
    build_depth_index(cfg)

    active_sessions = get_active_sessions()
    fetch_session_windows()

    seen_projects: set[str] = set()
    seen_depth_sessions: set[str] = set()

    entries: list[PickerEntry] = []
    entries += _collect_active_session_entries(
        cfg, active_sessions, seen_projects, seen_depth_sessions
    )
    entries += _collect_inactive_project_entries(
        cfg, seen_projects, seen_depth_sessions
    )

    if not entries:
        from rich.console import Console

        Console().print("[dim]No sessions or projects available.[/dim]")
        return

    selected = _run_fzf(
        _picker_format(entries),
        header="* = active  + = project | ESC to cancel",
        prompt="session> ",
    )
    if selected is None:
        return

    entry = PickerEntry.from_row(selected)
    _handle_selection(cfg, entry)


# ---------------------------------------------------------------------------
# cmd_switch
# ---------------------------------------------------------------------------


def cmd_switch() -> None:
    if not _require_fzf():
        raise SystemExit(1)

    active_sessions = get_active_sessions()
    if not active_sessions:
        error("No active tmux sessions.")
        raise SystemExit(1)

    cfg = parse_config()
    build_depth_index(cfg)
    fetch_session_windows()

    seen_projects: set[str] = set()
    seen_depth_sessions: set[str] = set()

    entries = _collect_active_session_entries(
        cfg,
        active_sessions,
        seen_projects,
        seen_depth_sessions,
        switch_mode=True,
    )

    if not entries:
        from rich.console import Console

        Console().print("[dim]No open sessions found.[/dim]")
        return

    selected = _run_fzf(
        _picker_format(entries),
        header="Open sessions | ESC to cancel",
        prompt="switch> ",
    )
    if selected is None:
        return

    entry = PickerEntry.from_row(selected)
    if entry.wt_path:
        open_worktree_in_session(entry.session, entry.wt_path)
    else:
        attach_or_switch(entry.session)


# ---------------------------------------------------------------------------
# Selection handler
# ---------------------------------------------------------------------------


def _handle_selection(cfg: ProjectConfig, entry: PickerEntry) -> None:
    from txs.commands import (  # late import to avoid circular dependency
        _attach_bare_repo,
        _ensure_session,
        cmd_attach,
    )

    match entry.marker:
        case "*":
            if entry.wt_path:
                open_worktree_in_session(entry.session, entry.wt_path)
            else:
                attach_or_switch(entry.session)

        case " ":
            if entry.wt_path and entry.session:
                open_worktree_in_session(entry.session, entry.wt_path)

        case "+":
            if entry.wt_path:
                basename = os.path.basename(entry.wt_path)
                proj_path = expand_path(get_project_prop(cfg, entry.project, "path"))

                if os.path.isdir(proj_path) and is_bare_repo(proj_path):
                    # Direct bare repo project worktree
                    cmd_attach(entry.project, basename)
                else:
                    # Depth-discovered repo (normal or bare worktree)
                    on_create = get_project_prop(cfg, entry.project, "on_create")
                    sname = sanitize_session_name(depth_session_name(entry.wt_path))
                    parent = os.path.dirname(entry.wt_path)

                    if is_bare_repo(parent):
                        created = _ensure_session(sname, parent, on_create) == "created"
                        _attach_bare_repo(
                            entry.project,
                            parent,
                            sname,
                            on_create,
                            basename,
                            created,
                        )
                    else:
                        _ensure_session(sname, entry.wt_path, on_create)
                        attach_or_switch(sname)
            else:
                cmd_attach(entry.project)
