"""
tmux wrappers — mirrors tmux.sh.

All functions call tmux via subprocess.  No state except the window-data cache
(SESSION_WINDOWS_DATA in bash → module-level dict here).
"""

from __future__ import annotations

import os
import subprocess

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_inside_tmux() -> bool:
    return bool(os.environ.get("TMUX"))


def session_exists(name: str) -> bool:
    result = subprocess.run(
        ["tmux", "has-session", "-t", f"={name}"],
        capture_output=True,
    )
    return result.returncode == 0


def sanitize_session_name(name: str) -> str:
    """tmux replaces '.' and ':' with '_' in session names."""
    return name.replace(".", "_").replace(":", "_")


def attach_or_switch(session_name: str) -> None:
    if is_inside_tmux():
        subprocess.run(["tmux", "switch-client", "-t", f"={session_name}"], check=True)
    else:
        subprocess.run(["tmux", "attach-session", "-t", f"={session_name}"], check=True)


def get_active_sessions() -> list[str]:
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [s for s in result.stdout.splitlines() if s]


# ---------------------------------------------------------------------------
# Window data cache  (replaces SESSION_WINDOWS_DATA bash global)
# ---------------------------------------------------------------------------

# Maps session_name -> list of window names
_window_cache: dict[str, list[str]] | None = None


def fetch_session_windows() -> None:
    """Pre-fetch all windows across all sessions."""
    global _window_cache
    _window_cache = {}
    result = subprocess.run(
        ["tmux", "list-windows", "-a", "-F", "#{session_name}:#{window_name}"],
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if not line:
            continue
        session, _, window = line.partition(":")
        _window_cache.setdefault(session, []).append(window)


def get_session_windows(session: str) -> str:
    """Return comma-separated window names for a session."""
    if _window_cache is None:
        fetch_session_windows()
    assert _window_cache is not None
    windows = _window_cache.get(session, [])
    return ", ".join(windows)


def invalidate_window_cache() -> None:
    global _window_cache
    _window_cache = None


# ---------------------------------------------------------------------------
# Window / worktree helpers
# ---------------------------------------------------------------------------


def find_window_by_path(session: str, worktree_path: str) -> str | None:
    """Return window index if any pane in the session is at worktree_path."""
    result = subprocess.run(
        [
            "tmux",
            "list-panes",
            "-t",
            f"={session}",
            "-a",
            "-F",
            "#{window_index}|#{pane_current_path}",
        ],
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if not line:
            continue
        win_index, _, pane_path = line.partition("|")
        if pane_path == worktree_path or pane_path.startswith(worktree_path + "/"):
            return win_index
    return None


def attach_or_switch_window(session: str, win_index: str) -> None:
    """Switch to a specific window in a session."""
    target = f"={session}:{win_index}"
    if is_inside_tmux():
        subprocess.run(["tmux", "switch-client", "-t", target], check=True)
        return

    has_tty = os.isatty(0) and os.isatty(1)
    if has_tty:
        subprocess.run(["tmux", "attach-session", "-t", target], check=True)
        return

    # Find any attached client and redirect it
    res = subprocess.run(
        ["tmux", "list-clients", "-F", "#{client_tty}"],
        capture_output=True,
        text=True,
    )
    clients = [line for line in res.stdout.splitlines() if line]
    if clients:
        subprocess.run(
            ["tmux", "switch-client", "-c", clients[0], "-t", target], check=True
        )
        return

    from txs.log import error

    error("Cannot attach to tmux: no interactive terminal or tmux client available.")
    raise SystemExit(1)


def open_worktree_in_session(
    session: str, worktree_path: str, on_create: str = ""
) -> None:
    """Switch to an existing window at worktree_path, or open a new one."""
    matched_win = find_window_by_path(session, worktree_path)
    if matched_win is not None:
        attach_or_switch_window(session, matched_win)
        return

    import os as _os

    result = subprocess.run(
        [
            "tmux",
            "new-window",
            "-a",
            "-t",
            f"={session}",
            "-n",
            _os.path.basename(worktree_path),
            "-c",
            worktree_path,
            "-P",
            "-F",
            "#{window_index}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    new_win = result.stdout.strip()

    if on_create:
        for cmd in on_create.splitlines():
            cmd = cmd.strip()
            if not cmd:
                continue
            subprocess.run(
                ["tmux", "send-keys", "-t", f"={session}:{new_win}", cmd, "Enter"],
                check=True,
            )

    attach_or_switch_window(session, new_win)
