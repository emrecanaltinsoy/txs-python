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
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-e", "-t", f"={session}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return f"[session '{session}' not available]"
        return result.stdout
