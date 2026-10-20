"""Preview panel — live tmux capture-pane output for the focused session."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static
from textual.widget import Widget


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
        """Called when a live preview timer is wired; debounce in the app if added."""
        if self._session:
            self._refresh_content()

    # ------------------------------------------------------------------

    def _refresh_content(self) -> None:
        content = self._capture(self._session)
        self.query_one("#preview-content", Static).update(content)

    @staticmethod
    def _capture(session: str) -> str:
        from txs.tmux import capture_active_pane

        return capture_active_pane(session) if session else ""
