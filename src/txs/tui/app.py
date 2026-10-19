"""TxsApp — main Textual application."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Input, Label

from txs.config import invalidate_config_cache, parse_config
from txs.tui.panels.preview import PreviewPanel
from txs.tui.panels.projects import ProjectNode, ProjectsPanel
from txs.tui.panels.sessions import SessionNode, SessionsPanel


class TxsApp(App):
    """lazygit-style tmux session manager."""

    CSS_PATH = Path(__file__).parent / "app.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("h", "prev_panel", "◀ panel", show=False, priority=True),
        Binding("l", "next_panel", "▶ panel", show=False, priority=True),
        Binding("j", "cursor_down", "▼", show=False, priority=True),
        Binding("k", "cursor_up", "▲", show=False, priority=True),
        Binding("a", "attach", "Attach"),
        Binding("x", "kill_session", "Kill"),
        Binding("slash", "start_filter", "Filter"),
        Binding("escape", "clear_filter", "Clear filter", show=False),
    ]

    _PANELS = ["sessions-tree", "projects-tree"]

    def __init__(self) -> None:
        super().__init__()
        self._cfg = None
        self._filter_active = False

    # ------------------------------------------------------------------
    # Helpers — always derived from self.focused, never stale
    # ------------------------------------------------------------------

    def _active_panel_id(self) -> str:
        focused = self.focused
        if focused is not None and getattr(focused, "id", None) in self._PANELS:
            return focused.id
        return self._PANELS[0]

    def _active_panel_idx(self) -> int:
        pid = self._active_panel_id()
        return self._PANELS.index(pid) if pid in self._PANELS else 0

    def _get_active_tree(self) -> SessionsPanel | ProjectsPanel | None:
        focused = self.focused
        if isinstance(focused, (SessionsPanel, ProjectsPanel)):
            return focused
        return None

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="left-col"):
                yield SessionsPanel()
                yield ProjectsPanel()
            yield PreviewPanel()
        with Horizontal(id="filter-bar"):
            yield Label("/ ", id="filter-label")
            yield Input(placeholder="type to filter...", id="filter-input")
        yield Footer()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self.query_one("#filter-bar").display = False
        self._load_config()
        self._refresh_all()
        self.query_one(SessionsPanel).focus()

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        try:
            self._cfg = parse_config()
        except SystemExit:
            self._cfg = None

    def _refresh_all(self) -> None:
        invalidate_config_cache()
        self._load_config()
        if self._cfg is None:
            return
        self.query_one(SessionsPanel).refresh_data(self._cfg)
        self.query_one(ProjectsPanel).refresh_data(self._cfg)
        self._update_preview()

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _update_preview(self) -> None:
        preview = self.query_one(PreviewPanel)
        session = self._focused_session()
        if session:
            preview.show_session(session)
        else:
            preview.clear_preview("Select a session to preview")

    def _focused_session(self) -> str:
        panel_id = self._active_panel_id()
        if panel_id == "sessions-tree":
            data = self.query_one(SessionsPanel).selected_node_data()
            if data:
                return data.session
        else:
            data = self.query_one(ProjectsPanel).selected_node_data()
            if isinstance(data, ProjectNode) and data.session_name:
                return data.session_name
        return ""

    # ------------------------------------------------------------------
    # Panel navigation
    # ------------------------------------------------------------------

    def action_next_panel(self) -> None:
        if self._filter_active:
            return
        idx = (self._active_panel_idx() + 1) % len(self._PANELS)
        self.query_one(f"#{self._PANELS[idx]}").focus()

    def action_prev_panel(self) -> None:
        if self._filter_active:
            return
        idx = (self._active_panel_idx() - 1) % len(self._PANELS)
        self.query_one(f"#{self._PANELS[idx]}").focus()

    def action_cursor_down(self) -> None:
        if self._filter_active:
            return
        panel = self._get_active_tree()
        if panel:
            panel.action_cursor_down()
            self._update_preview()

    def action_cursor_up(self) -> None:
        if self._filter_active:
            return
        panel = self._get_active_tree()
        if panel:
            panel.action_cursor_up()
            self._update_preview()

    def on_tree_cursor_moved(self) -> None:
        self._update_preview()

    def on_focus(self, _event) -> None:
        """Any focus change — sync preview and footer."""
        self._update_preview()
        self.refresh_bindings()

    # ------------------------------------------------------------------
    # Context-aware footer
    # ------------------------------------------------------------------

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        in_sessions = self._active_panel_id() == "sessions-tree"

        if self._filter_active:
            return action in ("clear_filter", "quit")

        match action:
            case "kill_session":
                return in_sessions
            case "attach" | "start_filter" | "refresh" | "quit":
                return True
            case _:
                return True

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_attach(self) -> None:
        panel_id = self._active_panel_id()

        if panel_id == "sessions-tree":
            data = self.query_one(SessionsPanel).selected_node_data()
            if data is None or not data.is_leaf:
                return
            self.app.exit(("attach_session", data.session, data.wt_path))

        else:
            data = self.query_one(ProjectsPanel).selected_node_data()
            if data is None or not isinstance(data, ProjectNode) or not data.is_leaf:
                return
            self.app.exit(("attach_project", data.project, data.path, data.wt_path, data.session_name))

    def action_kill_session(self) -> None:
        data = self.query_one(SessionsPanel).selected_node_data()
        if data and data.session:
            self.app.exit(("kill_session", data.session))

    def action_refresh(self) -> None:
        self.query_one("#filter-bar").display = False
        self.query_one("#filter-input", Input).value = ""
        self._filter_active = False
        for panel in [self.query_one(SessionsPanel), self.query_one(ProjectsPanel)]:
            panel.set_filter("")
            panel.border_title = panel.BORDER_TITLE
        self._refresh_all()
        self.refresh_bindings()

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------

    def action_start_filter(self) -> None:
        self._filter_active = True
        self.query_one("#filter-bar").display = True
        inp = self.query_one("#filter-input", Input)
        inp.value = ""
        inp.focus()
        self.refresh_bindings()

    def action_clear_filter(self) -> None:
        """Esc — clear filter and restore all results."""
        self._filter_active = False
        self.query_one("#filter-bar").display = False
        self.query_one("#filter-input", Input).value = ""
        panel = self._get_active_tree()
        if panel and self._cfg:
            panel.set_filter("")
            panel.refresh_data(self._cfg)
            panel.border_title = panel.BORDER_TITLE
        # Re-focus the active tree panel
        pid = self._active_panel_id()
        self.query_one(f"#{pid}").focus()
        self.refresh_bindings()

    def _dismiss_filter_bar(self) -> None:
        """Enter — hide bar, keep filter applied."""
        self._filter_active = False
        self.query_one("#filter-bar").display = False
        panel = self._get_active_tree()
        if panel:
            text = self.query_one("#filter-input", Input).value
            panel.border_title = (
                f"{panel.BORDER_TITLE}  [dim]/ {text}[/dim]" if text else panel.BORDER_TITLE
            )
        pid = self._active_panel_id()
        self.query_one(f"#{pid}").focus()
        self.refresh_bindings()

    def on_input_changed(self, event: Input.Changed) -> None:
        if not self._filter_active:
            return
        panel = self._get_active_tree()
        if panel and self._cfg:
            panel.set_filter(event.value)
            panel.refresh_data(self._cfg)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._dismiss_filter_bar()
