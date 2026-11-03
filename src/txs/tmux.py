"""
tmux wrappers — mirrors tmux.sh.

All functions call tmux via subprocess.  No state except the window-data cache
(SESSION_WINDOWS_DATA in bash → module-level dict here).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

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
        )

    @property
    def active_sessions(self) -> set[str]:
        return set(self.sessions)

    def windows_label(self, session: str) -> str:
        return ", ".join(self.windows_by_session.get(session, []))


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


# ---------------------------------------------------------------------------
# Worktree sessions — one tmux session per bare-repo worktree
# ---------------------------------------------------------------------------

WORKTREE_SESSION_MAX_LEN = 24  # default for `worktree_session_max_len`


def worktree_session_name(base: str, wt_path: str) -> str:
    """Session name for a worktree: ``<base>/<worktree>``.

    The worktree part is truncated when ``worktree_session_truncate`` is on
    (default) to ``worktree_session_max_len`` characters.
    """
    from txs.config import get_txs_setting, setting_bool

    name = os.path.basename(wt_path.rstrip("/"))
    if setting_bool("worktree_session_truncate", default=True):
        try:
            max_len = int(get_txs_setting("worktree_session_max_len") or 0)
        except ValueError:
            max_len = 0
        if max_len < 1:
            max_len = WORKTREE_SESSION_MAX_LEN
        name = name[:max_len]
    return sanitize_session_name(f"{base}/{name}")


def attach_worktree(base: str, wt_path: str, on_create: str = "") -> str:
    """Open (creating if needed) the worktree's session and switch to it.

    ``on_create`` runs once, when the session is first created.
    Returns the session name.
    """
    session = worktree_session_name(base, wt_path)
    if not session_exists(session):
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session, "-c", wt_path],
            check=True,
        )
        for cmd in on_create.splitlines():
            cmd = cmd.strip()
            if cmd:
                subprocess.run(
                    ["tmux", "send-keys", "-t", f"={session}:", cmd, "Enter"],
                    check=True,
                )
    attach_or_switch(session)
    return session
