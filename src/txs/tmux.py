"""
tmux wrappers — mirrors tmux.sh.

All functions call tmux via subprocess.  No state except the window-data cache
(SESSION_WINDOWS_DATA in bash → module-level dict here).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

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
    worktree_path = worktree_path.rstrip("/") or "/"
    prefix = worktree_path.rstrip("/") + "/"
    result = subprocess.run(
        [
            "tmux",
            "list-panes",
            "-t",
            f"={session}",
            "-s",
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
        if pane_path == worktree_path or pane_path.startswith(prefix):
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


# ---------------------------------------------------------------------------
# Agent helpers
# ---------------------------------------------------------------------------


@dataclass
class AgentInfo:
    session: str
    pane_id: str  # %N — unique pane id
    pane_index: str  # window-relative pane index
    title: str  # pane title (user label @ branch)
    command: str  # pane_current_command

    @property
    def is_running(self) -> bool:
        return self.command == "pi"


AGENTS_WINDOW = "agents"


@dataclass
class TmuxSnapshot:
    """One round of tmux queries for TUI panel refresh."""

    sessions: tuple[str, ...]
    windows_by_session: dict[str, list[str]]
    agents: list[AgentInfo]
    pane_locations: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    # session -> [(window_index, pane_current_path), ...]

    @classmethod
    def fetch(cls) -> TmuxSnapshot:
        sessions = tuple(get_active_sessions())

        windows_by_session: dict[str, list[str]] = {}
        win_result = subprocess.run(
            ["tmux", "list-windows", "-a", "-F", "#{session_name}:#{window_name}"],
            capture_output=True,
            text=True,
        )
        if win_result.returncode == 0:
            for line in win_result.stdout.splitlines():
                if not line:
                    continue
                session, _, window = line.partition(":")
                if session and window:
                    windows_by_session.setdefault(session, []).append(window)

        agents: list[AgentInfo] = []
        pane_locations: dict[str, list[tuple[str, str]]] = {}
        pane_result = subprocess.run(
            [
                "tmux",
                "list-panes",
                "-a",
                "-F",
                "#{session_name}|#{window_name}|#{window_index}|#{pane_current_path}|#{pane_id}|#{pane_index}|#{@txs_label}|#{pane_current_command}",
            ],
            capture_output=True,
            text=True,
        )
        if pane_result.returncode == 0:
            for line in pane_result.stdout.splitlines():
                if not line:
                    continue
                parts = line.split("|", 7)
                if len(parts) != 8:
                    continue
                (
                    session,
                    window,
                    win_index,
                    pane_path,
                    pane_id,
                    pane_index,
                    label,
                    command,
                ) = parts
                pane_locations.setdefault(session, []).append((win_index, pane_path))
                if window == AGENTS_WINDOW:
                    agents.append(
                        AgentInfo(
                            session=session,
                            pane_id=pane_id,
                            pane_index=pane_index,
                            title=label or command,
                            command=command,
                        )
                    )

        global _window_cache
        _window_cache = {k: list(v) for k, v in windows_by_session.items()}

        return cls(
            sessions=sessions,
            windows_by_session=windows_by_session,
            agents=agents,
            pane_locations=pane_locations,
        )

    @property
    def active_sessions(self) -> set[str]:
        return set(self.sessions)

    def windows_label(self, session: str) -> str:
        return ", ".join(self.windows_by_session.get(session, []))

    def window_for_path(self, session: str, worktree_path: str) -> str | None:
        """Return window index if any pane in session is at worktree_path."""
        worktree_path = worktree_path.rstrip("/") or "/"
        prefix = worktree_path.rstrip("/") + "/"
        for win_index, pane_path in self.pane_locations.get(session, []):
            if pane_path == worktree_path or pane_path.startswith(prefix):
                return win_index
        return None


def get_agents() -> list[AgentInfo]:
    """Return all panes inside windows named 'agents' across all sessions."""
    result = subprocess.run(
        [
            "tmux",
            "list-panes",
            "-a",
            "-F",
            "#{session_name}|#{window_name}|#{pane_id}|#{pane_index}|#{@txs_label}|#{pane_current_command}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    agents = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        session, window, pane_id, pane_index, label, command = line.split("|", 5)
        if window != AGENTS_WINDOW:
            continue
        agents.append(
            AgentInfo(
                session=session,
                pane_id=pane_id,
                pane_index=pane_index,
                title=label or command,
                command=command,
            )
        )
    return agents


def _agents_window_exists(session: str) -> bool:
    result = subprocess.run(
        ["tmux", "list-windows", "-t", session, "-F", "#{window_name}"],
        capture_output=True,
        text=True,
    )
    return AGENTS_WINDOW in result.stdout.splitlines()


def _set_agent_label(pane_id: str, label: str) -> None:
    """Store label as a tmux pane user option — survives shell title overwrites."""
    subprocess.run(
        ["tmux", "set-option", "-p", "-t", pane_id, "@txs_label", label],
        check=True,
    )


def launch_agent(session: str, label: str, cwd: str) -> None:
    """
    Open a new pane in the 'agents' window of session (creating the window
    if needed), set its title to label, and start pi.
    """
    if not _agents_window_exists(session):
        # Use "session:" (append to end) — "=session" resolves to a window
        # position and can collide with an existing index.
        # -P -F gives us the new pane id so we can target it directly.
        result = subprocess.run(
            [
                "tmux",
                "new-window",
                "-t",
                f"{session}:",
                "-n",
                AGENTS_WINDOW,
                "-c",
                cwd,
                "-P",
                "-F",
                "#{pane_id}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        pane_id = result.stdout.strip()
        _set_agent_label(pane_id, label)
        subprocess.run(["tmux", "send-keys", "-t", pane_id, "pi", "Enter"], check=True)
    else:
        # Split horizontally inside the agents window
        result = subprocess.run(
            [
                "tmux",
                "split-window",
                "-h",
                "-t",
                f"={session}:{AGENTS_WINDOW}",
                "-c",
                cwd,
                "-P",
                "-F",
                "#{pane_id}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        pane_id = result.stdout.strip()
        _set_agent_label(pane_id, label)
        subprocess.run(["tmux", "send-keys", "-t", pane_id, "pi", "Enter"], check=True)


def kill_session_inplace(session: str) -> None:
    """Kill a tmux session without printing (safe while a TUI is running)."""
    if not session_exists(session):
        return
    if is_inside_tmux():
        cur = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_name}"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if cur == session:
            subprocess.run(["tmux", "switch-client", "-l"])
    subprocess.run(["tmux", "kill-session", "-t", f"={session}"], check=True)


def kill_agent(pane_id: str, session: str) -> None:
    """Kill an agent pane; remove the agents window if it was the last pane."""
    # Count panes in the agents window before killing
    result = subprocess.run(
        [
            "tmux",
            "list-panes",
            "-t",
            f"={session}:{AGENTS_WINDOW}",
            "-F",
            "#{pane_id}",
        ],
        capture_output=True,
        text=True,
    )
    pane_count = len([line for line in result.stdout.splitlines() if line])
    subprocess.run(["tmux", "kill-pane", "-t", pane_id], check=True)
    if pane_count <= 1:
        # Was the last pane — window is already gone, nothing more to do
        pass


def switch_to_agent(session: str, pane_id: str) -> None:
    """Attach to session, switch to agents window, focus the given pane."""
    subprocess.run(
        ["tmux", "select-window", "-t", f"={session}:{AGENTS_WINDOW}"],
        check=True,
    )
    subprocess.run(["tmux", "select-pane", "-t", pane_id], check=True)
    attach_or_switch(session)


def get_session_worktree_paths(session: str) -> list[tuple[str, str]]:
    """
    Return (path, name) pairs for every open window in session whose
    pane cwd looks like a worktree (i.e. has an open pane with a real path).
    Used to offer a cwd picker when launching an agent.
    """
    # list-windows to get windows for this session, then list-panes per window
    wins = subprocess.run(
        ["tmux", "list-windows", "-t", session, "-F", "#{window_name}"],
        capture_output=True,
        text=True,
    )
    seen: dict[str, str] = {}
    for window in wins.stdout.splitlines():
        if not window or window == AGENTS_WINDOW:
            continue
        result = subprocess.run(
            [
                "tmux",
                "list-panes",
                "-t",
                f"{session}:{window}",
                "-F",
                "#{pane_current_path}",
            ],
            capture_output=True,
            text=True,
        )
        for path in result.stdout.splitlines():
            if path and path not in seen:
                seen[path] = window
    return [(path, name) for path, name in seen.items()]


def capture_active_pane(session: str) -> str:
    """Return the text content of the active pane in session, or an empty string."""
    panes = subprocess.run(
        ["tmux", "list-panes", "-t", f"={session}", "-F", "#{pane_active}:#{pane_id}"],
        capture_output=True,
        text=True,
    )
    if panes.returncode != 0 or not panes.stdout.strip():
        return ""
    pane_id = next(
        (
            line.split(":", 1)[1]
            for line in panes.stdout.splitlines()
            if line.startswith("1:")
        ),
        None,
    )
    if not pane_id:
        return ""
    result = subprocess.run(
        ["tmux", "capture-pane", "-p", "-t", pane_id],
        capture_output=True,
        text=True,
        errors="replace",
    )
    return result.stdout if result.returncode == 0 else ""


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
