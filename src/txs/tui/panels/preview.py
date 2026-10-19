"""Preview panel — live tmux capture-pane output for the focused session."""

from __future__ import annotations

import subprocess

from textual.app import ComposeResult
from textual.widgets import Static
from textual.widget import Widget
from textual.scroll_view import ScrollView


class PreviewPanel(Widget):
    """Shows a live snapshot of the focused tmux session's active pane."""

    BORDER_TITLE = "Preview"

    def __init__(self) -> None:
        super().__init__(id="preview-panel")
        self._session: str = ""

    def compose(self) -> ComposeResult:
        yield Static("", id="preview-content", markup=False)

    def show_session(self, session: str) -> None:
        """Capture and display the given session's active pane."""
        if session == self._session and session:
            self._refresh_content()
            return
        self._session = session
        self._refresh_content()

    def clear_preview(self, message: str = "") -> None:
        self._session = ""
        self.query_one("#preview-content", Static).update(message)

    def refresh_preview(self) -> None:
        """Called by the auto-refresh timer."""
        if self._session:
            self._refresh_content()

    # ------------------------------------------------------------------

    def _refresh_content(self) -> None:
        content = self._capture(self._session)
        self.query_one("#preview-content", Static).update(content)

    @staticmethod
    def _capture(session: str) -> str:
        if not session:
            return ""
        # capture-pane -t "=name" fails as a pane target in tmux 3.7+
        # (rc=1, error on stderr). list-panes -t "=name" resolves correctly;
        # capture by pane ID instead.
        panes = subprocess.run(
            ["tmux", "list-panes", "-t", f"={session}", "-F", "#{pane_active}:#{pane_id}"],
            capture_output=True,
            text=True,
        )
        if panes.returncode != 0 or not panes.stdout.strip():
            return "(session not active)"
        pane_id = None
        for line in panes.stdout.strip().splitlines():
            active, _, pid = line.partition(":")
            if active == "1":
                pane_id = pid
                break
        if not pane_id:
            return "(session not active)"
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", pane_id],
            capture_output=True,
            text=True,
            errors="replace",
        )
        if result.returncode != 0:
            return "(capture failed)"
        return result.stdout
