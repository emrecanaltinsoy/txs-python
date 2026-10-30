"""TxsApp — main Textual application."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Footer, HelpPanel, Input, Label, ListItem, ListView
from textual.worker import Worker, WorkerState

from txs.config import parse_config
from txs.tmux import (
    get_active_sessions as _get_active_sessions,
    get_session_worktree_paths,
    kill_agent,
    kill_session_inplace,
    launch_agent,
)
from txs.tui.sync import TuiRefreshBundle, fetch_refresh_bundle, maybe_reload_config
from txs.tui.fzf import fzf_available, run_fzf_pick
from txs.tui.panels.agents import AgentNode, AgentsPanel
from txs.tui.panels.base import TxsTreePanel
from txs.tui.panels.preview import PreviewPanel
from txs.tui.panels.projects import ProjectNode, ProjectsPanel
from txs.tui.panels.sessions import SessionsPanel
from txs.tui.theme import apply_saved_theme, open_theme_palette, persist_theme

# ---------------------------------------------------------------------------
# Modal screens
# ---------------------------------------------------------------------------


_FZF_PANEL_TITLES = {
    "sessions-tree": "Sessions",
    "projects-tree": "Projects",
    "agents-tree": "Agents",
}


class LabelInputScreen(ModalScreen[str | None]):
    """Prompt for an agent label. Returns the label string or None on cancel."""

    CSS = """
    LabelInputScreen {
        align: center middle;
    }
    #label-dialog {
        width: 60;
        height: auto;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #label-prompt {
        height: auto;
        margin-bottom: 1;
    }
    #label-input {
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="label-dialog"):
            yield Label("Agent label (leave blank to use 'pi'):", id="label-prompt")
            yield Input(placeholder="e.g. auth refactor", id="label-input")

    def on_mount(self) -> None:
        self.query_one("#label-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Submit a label, preserving an empty string for the default label."""
        self.dismiss(event.value.strip())

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.stop()


class _NavListView(ListView):
    """ListView with j/k bindings."""

    BINDINGS = [
        *ListView.BINDINGS,
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
    ]


def _truncate_path(path: str, max_len: int = 40) -> str:
    """Keep the last component intact; abbreviate the middle with '..'.

    '/very/long/path/to/session' → '/very/../session' when over max_len.
    """
    if len(path) <= max_len:
        return path
    import os

    head, tail = os.path.split(path)
    # Already short enough with just the last component?
    if len(tail) >= max_len:
        return tail
    # Walk up until head + '/..' + tail fits
    while head and len(head) + len(tail) + 4 > max_len:  # 4 = '/..' + '/'
        head = os.path.dirname(head)
    prefix = head if head != "/" else ""
    return f"{prefix}/../{tail}"


class CwdPickerScreen(ModalScreen[str | None]):
    """Pick a cwd from open windows in a session. Returns path or None on cancel."""

    CSS = """
    CwdPickerScreen {
        align: center middle;
    }
    #cwd-dialog {
        width: 70;
        height: auto;
        max-height: 20;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #cwd-prompt {
        height: auto;
        margin-bottom: 1;
    }
    #cwd-list {
        height: auto;
        max-height: 12;
    }
    """

    def __init__(
        self, session: str, paths: list[tuple[str, str]], fallback: str
    ) -> None:
        super().__init__()
        self._session = session
        self._paths = paths  # [(path, window_name), ...]
        self._fallback = fallback  # session root from config

    def compose(self) -> ComposeResult:
        with Vertical(id="cwd-dialog"):
            yield Label(f"Start agent in ({self._session}):", id="cwd-prompt")
            items: list[ListItem] = []
            for path, name in self._paths:
                short = _truncate_path(path)
                items.append(
                    ListItem(
                        Label(f"  {name}  [dim]{short}[/dim]"), id=f"p-{len(items)}"
                    )
                )
            if self._fallback and (
                not self._paths or self._fallback not in [p for p, _ in self._paths]
            ):
                short = _truncate_path(self._fallback)
                items.append(
                    ListItem(
                        Label(f"  (session root)  [dim]{short}[/dim]"), id="p-fallback"
                    )
                )
            yield _NavListView(*items, id="cwd-list")

    def on_mount(self) -> None:
        self.query_one("#cwd-list", _NavListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx_str = event.item.id or ""
        if idx_str == "p-fallback":
            self.dismiss(self._fallback)
        else:
            try:
                idx = int(idx_str.replace("p-", ""))
                self.dismiss(self._paths[idx][0])
            except (ValueError, IndexError):
                self.dismiss(self._fallback)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.stop()


class ConfirmKillScreen(ModalScreen[bool]):
    """Confirm killing a session. 'y' confirms; any other key means No (default)."""

    CSS = """
    ConfirmKillScreen {
        align: center middle;
    }
    #confirm-dialog {
        width: 60;
        height: auto;
        border: round $error;
        background: $surface;
        padding: 1 2;
    }
    #confirm-prompt {
        height: auto;
    }
    """

    def __init__(self, session: str) -> None:
        super().__init__()
        self._session = session

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(f"Kill session '{self._session}'? [y/N]", id="confirm-prompt")

    def on_key(self, event) -> None:
        self.dismiss(event.key == "y")
        event.stop()


class SessionPickerScreen(ModalScreen[str | None]):
    """Pick an active session. Returns session name or None on cancel."""

    CSS = """
    SessionPickerScreen {
        align: center middle;
    }
    #session-dialog {
        width: 50;
        height: auto;
        max-height: 20;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #session-prompt {
        height: auto;
        margin-bottom: 1;
    }
    #session-list {
        height: auto;
        max-height: 12;
    }
    """

    def __init__(self, sessions: list[str]) -> None:
        super().__init__()
        self._sessions = sessions

    def compose(self) -> ComposeResult:
        with Vertical(id="session-dialog"):
            yield Label("Launch agent in session:", id="session-prompt")
            items = [
                ListItem(Label(f"  {s}"), id=f"s-{i}")
                for i, s in enumerate(self._sessions)
            ]
            yield _NavListView(*items, id="session-list")

    def on_mount(self) -> None:
        self.query_one("#session-list", _NavListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx_str = event.item.id or ""
        try:
            idx = int(idx_str.replace("s-", ""))
            self.dismiss(self._sessions[idx])
        except (ValueError, IndexError):
            self.dismiss(None)

    def on_key(self, event) -> None:
        lv = self.query_one("#session-list", ListView)
        if event.key == "j":
            lv.action_cursor_down()
            event.stop()
        elif event.key == "k":
            lv.action_cursor_up()
            event.stop()
        elif event.key == "escape":
            self.dismiss(None)
            event.stop()


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------


class TxsApp(App):
    """lazygit-style tmux session manager."""

    CSS_PATH = Path(__file__).parent / "app.tcss"
    BINDING_GROUP_TITLE = "General"
    _LAZY_STARTUP_WORKER = "lazy_startup_fetch"
    _LOADING_SUFFIX = "  …"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("question_mark", "toggle_help_panel", "Keys"),
        Binding("h", "prev_panel", "◀ panel", show=False),
        Binding("l", "next_panel", "▶ panel", show=False),
        Binding("j", "cursor_down", "▼", show=False),
        Binding("k", "cursor_up", "▲", show=False),
        Binding("s", "attach", "Switch", key_display="s/↵"),
        Binding("a", "new_agent", "New agent"),
        Binding("x", "kill", "Kill"),
        Binding("slash", "start_filter", "Filter"),
        Binding("escape", "clear_filter", "Clear filter", show=False),
    ]

    _PANELS = ["sessions-tree", "projects-tree", "agents-tree"]
    _FILTER_DEBOUNCE_SEC = 0.2

    def __init__(self) -> None:
        super().__init__()
        self._cfg = None
        self._tmux = None
        self._filter_active = False
        self._filter_panel_id: str = "sessions-tree"
        self._filter_refresh_timer = None
        self._lazy_startup_bundle: TuiRefreshBundle | None = None
        apply_saved_theme(self)

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

    def _get_active_tree(self) -> SessionsPanel | ProjectsPanel | AgentsPanel | None:
        focused = self.focused
        if isinstance(focused, (SessionsPanel, ProjectsPanel, AgentsPanel)):
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
                yield AgentsPanel()
            yield PreviewPanel()
        with Horizontal(id="filter-bar"):
            yield Label("/ ", id="filter-label")
            yield Input(placeholder="type to filter...", id="filter-input")
        yield Footer()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self.theme_changed_signal.subscribe(self, persist_theme)
        self.query_one("#filter-bar").display = False
        maybe_reload_config()
        self._load_config()
        self.query_one(SessionsPanel).focus()
        if self._cfg is None:
            self.query_one(PreviewPanel).clear_preview(
                "Config not found — check ~/.config/txs/projects.conf"
            )
            return
        self._set_tree_panels_loading(True)
        self.query_one(PreviewPanel).clear_preview("")
        self.call_after_refresh(self._begin_lazy_startup)

    def _begin_lazy_startup(self) -> None:
        self.run_worker(
            fetch_refresh_bundle,
            name=self._LAZY_STARTUP_WORKER,
            thread=True,
            exclusive=True,
            group="startup",
        )

    @on(Worker.StateChanged)
    def _on_lazy_startup_worker(self, event: Worker.StateChanged) -> None:
        if event.worker.name != self._LAZY_STARTUP_WORKER:
            return
        if event.state == WorkerState.ERROR:
            self._set_tree_panels_loading(False)
            self.query_one(PreviewPanel).clear_preview(
                "Failed to load tmux state (is tmux running?)"
            )
            return
        if event.state != WorkerState.SUCCESS:
            return
        self._lazy_startup_bundle = event.worker.result
        self._tmux = self._lazy_startup_bundle.snap
        self.call_later(self._lazy_startup_sessions)

    def _lazy_startup_sessions(self) -> None:
        bundle = self._lazy_startup_bundle
        if bundle is None or self._cfg is None:
            return
        self._restore_panel_title(SessionsPanel)
        self._refresh_sessions_panel(bundle)
        children = list(self.query_one(SessionsPanel).root.children)
        if children:
            self.query_one(SessionsPanel).move_cursor(children[0])
        self._update_preview("sessions-tree")
        self.call_later(self._lazy_startup_agents)

    def _lazy_startup_agents(self) -> None:
        bundle = self._lazy_startup_bundle
        if bundle is None:
            return
        self._restore_panel_title(AgentsPanel)
        self._refresh_agents_panel(bundle)
        self.call_later(self._lazy_startup_projects)

    def _lazy_startup_projects(self) -> None:
        bundle = self._lazy_startup_bundle
        if bundle is None or self._cfg is None:
            return
        self._restore_panel_title(ProjectsPanel)
        self._refresh_projects_panel(bundle)
        self._select_first_items()
        self.query_one(SessionsPanel).focus()
        self._lazy_startup_bundle = None

    def _select_first_items(self) -> None:
        """On startup only: move cursor to first item in each panel."""
        for panel in [self.query_one(SessionsPanel), self.query_one(ProjectsPanel)]:
            children = list(panel.root.children)
            if children:
                panel.move_cursor(children[0])
        agents = self.query_one(AgentsPanel)
        children = list(agents.root.children)
        if children:
            agents.move_cursor(children[0])

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        try:
            self._cfg = parse_config()
        except SystemExit:
            self._cfg = None

    def _set_tree_panels_loading(self, loading: bool) -> None:
        for panel_type in (SessionsPanel, ProjectsPanel, AgentsPanel):
            panel = self.query_one(panel_type)
            panel.border_title = (
                panel.BORDER_TITLE + self._LOADING_SUFFIX
                if loading
                else panel.BORDER_TITLE
            )

    def _restore_panel_title(self, panel_type: type) -> None:
        panel = self.query_one(panel_type)
        panel.border_title = panel.BORDER_TITLE

    def _refresh_sessions_panel(self, bundle: TuiRefreshBundle) -> None:
        if self._cfg is None:
            return
        self.query_one(SessionsPanel).refresh_data(
            self._cfg, bundle.snap, bundle.settings
        )

    def _refresh_projects_panel(self, bundle: TuiRefreshBundle) -> None:
        if self._cfg is None:
            return
        self.query_one(ProjectsPanel).refresh_data(
            self._cfg, bundle.snap, bundle.settings
        )

    def _refresh_agents_panel(self, bundle: TuiRefreshBundle) -> None:
        self.query_one(AgentsPanel).refresh_data(bundle.snap, bundle.settings)

    def _apply_refresh_bundle(self, bundle: TuiRefreshBundle) -> None:
        if self._cfg is None:
            return
        self._tmux = bundle.snap
        self._refresh_sessions_panel(bundle)
        self._refresh_projects_panel(bundle)
        self._refresh_agents_panel(bundle)
        self._update_preview()

    def _sync_panels(self, *, reload_config: bool = False) -> None:
        if reload_config or self._cfg is None:
            maybe_reload_config()
            self._load_config()
        if self._cfg is None:
            return
        self._apply_refresh_bundle(fetch_refresh_bundle())

    def _refresh_all(self) -> None:
        self._sync_panels(reload_config=True)

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _update_preview(self, panel_id: str | None = None) -> None:
        panel_id = panel_id or self._active_panel_id()
        preview = self.query_one(PreviewPanel)

        if panel_id == "sessions-tree":
            data = self.query_one(SessionsPanel).selected_node_data()
            session = data.session if data else ""
            if session:
                preview.show_session(session)
            else:
                preview.clear_preview("Select a session to preview")

        elif panel_id == "projects-tree":
            data = self.query_one(ProjectsPanel).selected_node_data()
            if isinstance(data, ProjectNode) and data.session_name:
                active = (
                    self._tmux.active_sessions
                    if self._tmux is not None
                    else set(_get_active_sessions())
                )
                if data.session_name in active:
                    preview.show_session(data.session_name)
                else:
                    preview.clear_preview(
                        f"  {data.project}\n  {data.wt_path or data.path}\n\n  Inactive — press 's' to start"
                    )
            else:
                preview.clear_preview("Select a project to preview")

        else:  # agents-tree
            data = self.query_one(AgentsPanel).selected_node_data()
            if isinstance(data, AgentNode) and data.is_leaf:
                preview.show_session(data.session)
            elif isinstance(data, AgentNode):
                preview.clear_preview(
                    f"  {data.session}\n\n  Select an agent to preview"
                )
            else:
                preview.clear_preview("Select an agent to preview")

    # ------------------------------------------------------------------
    # Panel navigation
    # ------------------------------------------------------------------

    def action_next_panel(self) -> None:
        if self._filter_active or len(self.screen_stack) > 1:
            return
        idx = (self._active_panel_idx() + 1) % len(self._PANELS)
        self.query_one(f"#{self._PANELS[idx]}").focus()
        self._update_preview(self._PANELS[idx])

    def action_prev_panel(self) -> None:
        if self._filter_active or len(self.screen_stack) > 1:
            return
        idx = (self._active_panel_idx() - 1) % len(self._PANELS)
        self.query_one(f"#{self._PANELS[idx]}").focus()
        self._update_preview(self._PANELS[idx])

    def action_cursor_down(self) -> None:
        if self._filter_active or len(self.screen_stack) > 1:
            return
        panel = self._get_active_tree()
        if panel:
            panel.action_cursor_down()
            self._update_preview()

    def action_cursor_up(self) -> None:
        if self._filter_active or len(self.screen_stack) > 1:
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

    def action_change_theme(self) -> None:
        open_theme_palette(self)

    def action_toggle_help_panel(self) -> None:
        if len(self.screen_stack) > 1:
            return
        try:
            self.screen.query_one(HelpPanel)
        except NoMatches:
            self.action_show_help_panel()
        else:
            self.action_hide_help_panel()

    # ------------------------------------------------------------------
    # Context-aware footer
    # ------------------------------------------------------------------

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        pid = self._active_panel_id()

        if self._filter_active:
            return action in ("clear_filter", "quit", "toggle_help_panel")

        if action == "clear_filter":
            return bool(self._tree_panel_filter(pid))

        match action:
            case "toggle_help_panel":
                return len(self.screen_stack) <= 1
            case "kill":
                # kill_session only in sessions panel; kill_agent only in agents panel
                return pid in ("sessions-tree", "agents-tree")
            case "attach":
                return pid != "agents-tree"
            case "new_agent":
                return pid in ("sessions-tree", "agents-tree")
            case "start_filter":
                if fzf_available():
                    return pid in self._PANELS
                return pid in ("sessions-tree", "projects-tree")
            case "refresh" | "quit":
                return True
            case _:
                return True

    # ------------------------------------------------------------------
    # Actions — attach / switch
    # ------------------------------------------------------------------

    def _attach_selected_session(self) -> None:
        data = self.query_one(SessionsPanel).selected_node_data()
        if data is None or not data.is_leaf:
            return
        self.app.exit(("attach_session", data.session, data.wt_path))

    def action_attach(self) -> None:
        pid = self._active_panel_id()
        if pid == "sessions-tree":
            self._attach_selected_session()
        elif pid == "projects-tree":
            data = self.query_one(ProjectsPanel).selected_node_data()
            if data is None or not isinstance(data, ProjectNode) or not data.is_leaf:
                return
            self.app.exit(
                (
                    "attach_project",
                    data.project,
                    data.path,
                    data.wt_path,
                    data.session_name,
                )
            )

    def on_key(self, event) -> None:
        if event.key == "enter":
            if isinstance(self.focused, (SessionsPanel, ProjectsPanel)):
                self.action_attach()
                event.stop()
            elif isinstance(self.focused, AgentsPanel):
                self._switch_to_selected_agent()
                event.stop()

    # ------------------------------------------------------------------
    # Actions — kill
    # ------------------------------------------------------------------

    def action_kill(self) -> None:
        pid = self._active_panel_id()
        if pid == "sessions-tree":
            data = self.query_one(SessionsPanel).selected_node_data()
            if data and data.session:
                session = data.session

                def _on_confirm(confirmed: bool | None) -> None:
                    if confirmed:
                        kill_session_inplace(session)
                        self._sync_panels()

                self.push_screen(ConfirmKillScreen(session), _on_confirm)
        elif pid == "agents-tree":
            data = self.query_one(AgentsPanel).selected_node_data()
            if data and data.is_leaf and data.pane_id:
                kill_agent(data.pane_id, data.session)
                if self._cfg is not None:
                    bundle = fetch_refresh_bundle()
                    self.query_one(AgentsPanel).refresh_data(
                        bundle.snap, bundle.settings
                    )
                    self._tmux = bundle.snap

    # ------------------------------------------------------------------
    # Actions — agents
    # ------------------------------------------------------------------

    def _switch_to_selected_agent(self) -> None:
        data = self.query_one(AgentsPanel).selected_node_data()
        if data is None or not data.is_leaf or not data.pane_id:
            return
        self.app.exit(("attach_agent", data.session, data.pane_id))

    def action_new_agent(self) -> None:
        pid = self._active_panel_id()
        if pid == "sessions-tree":
            data = self.query_one(SessionsPanel).selected_node_data()
            session = data.session if data else ""
        elif pid == "agents-tree":
            data = self.query_one(AgentsPanel).selected_node_data()
            session = data.session if data else ""
        else:
            return

        if not session:
            # No session focused — show picker
            sessions = _get_active_sessions()
            if not sessions:
                return
            self.push_screen(SessionPickerScreen(sessions), self._on_session_picked)
            return

        self._start_agent_flow(session)

    def _on_session_picked(self, session: str | None) -> None:
        if session:
            self._start_agent_flow(session)

    def _start_agent_flow(self, session: str) -> None:
        self.push_screen(
            LabelInputScreen(), lambda label: self._on_label_entered(session, label)
        )

    def _on_label_entered(self, session: str, label: str | None) -> None:
        """Choose the agent directory unless the label dialog was cancelled."""
        if label is None:
            return
        # Resolve cwd
        paths = get_session_worktree_paths(session)
        if len(paths) == 1:
            self._launch(session, label, paths[0][0])
        elif len(paths) > 1:
            # Get session root as fallback
            fallback = paths[0][0] if paths else ""
            self.push_screen(
                CwdPickerScreen(session, paths, fallback),
                lambda cwd: self._on_cwd_picked(session, label, cwd),
            )
        else:
            # No open windows to pick from — use session root from config
            cwd = self._session_root(session)
            self._launch(session, label, cwd)

    def _on_cwd_picked(self, session: str, label: str | None, cwd: str | None) -> None:
        if cwd is None:
            return  # user cancelled cwd picker
        self._launch(session, label, cwd)

    def _launch(self, session: str, label: str | None, cwd: str) -> None:
        import os

        final_label = label if label else "pi"
        # Append branch/dir suffix: "label @ dirname"
        branch = os.path.basename(cwd)
        display = f"{final_label} @ {branch}" if branch else final_label
        launch_agent(session, display, cwd)
        self.app.exit(("attach_agent", session, None))

    def _session_root(self, session: str) -> str:
        """Get the project path for a session from config, fallback to $HOME."""
        import os

        if self._cfg is None:
            return os.path.expanduser("~")
        from txs.config import expand_path, find_project_for_session, get_project_prop

        proj = find_project_for_session(self._cfg, session)
        if proj:
            return expand_path(get_project_prop(self._cfg, proj, "path"))
        return os.path.expanduser("~")

    # ------------------------------------------------------------------
    # Actions — refresh
    # ------------------------------------------------------------------

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

    def _tree_panel_filter(self, panel_id: str | None) -> str:
        if panel_id == "sessions-tree":
            return self.query_one(SessionsPanel)._filter
        if panel_id == "projects-tree":
            return self.query_one(ProjectsPanel)._filter
        return ""

    def action_start_filter(self) -> None:
        """'/' — fzf picker when installed; otherwise the inline filter."""
        pid = self._active_panel_id()
        if fzf_available():
            self._open_fzf_picker(pid)
        elif pid in ("sessions-tree", "projects-tree"):
            self._start_inline_filter()

    def _open_fzf_picker(self, pid: str) -> None:
        """Hand the terminal to fzf, then run the panel's Enter action on the pick."""
        panel = self.query_one(f"#{pid}", TxsTreePanel)
        leaves = panel.leaf_nodes()
        labels = [panel.leaf_label(node) for node in leaves]
        title = _FZF_PANEL_TITLES.get(pid, "Select")
        try:
            with self.suspend():
                if not leaves:
                    return
                idx = run_fzf_pick(
                    labels,
                    header=f"{title}  (Enter: open, Esc: cancel)",
                    prompt=f"{title.lower()}> ",
                )
        except SuspendNotSupported:
            # Terminal can't hand over (e.g. headless): keep the inline filter.
            if pid in ("sessions-tree", "projects-tree"):
                self._start_inline_filter()
            return
        panel.focus()
        if idx is None:
            return
        panel.reveal_node(leaves[idx])
        if pid == "agents-tree":
            self._switch_to_selected_agent()
        else:
            self.action_attach()

    def _start_inline_filter(self) -> None:
        self._filter_panel_id = self._active_panel_id()
        self._filter_active = True
        self.query_one("#filter-bar").display = True
        inp = self.query_one("#filter-input", Input)
        inp.value = ""
        inp.focus()
        self.refresh_bindings()

    def action_clear_filter(self) -> None:
        """Esc — clear filter and restore all results."""
        if self._filter_active:
            panel_id = self._filter_panel_id
        else:
            panel_id = self._active_panel_id()
            if not self._tree_panel_filter(panel_id):
                return
        self._filter_active = False
        self.query_one("#filter-bar").display = False
        self.query_one("#filter-input", Input).value = ""
        panel = self.query_one(f"#{panel_id}")
        if self._cfg and isinstance(panel, (SessionsPanel, ProjectsPanel)):
            panel.set_filter("")
            self._sync_panels(reload_config=False)
            panel.border_title = panel.BORDER_TITLE
        self.query_one(f"#{panel_id}").focus()
        self.refresh_bindings()

    def _dismiss_filter_bar(self) -> None:
        """Enter — hide bar, keep filter applied, restore focus to the panel that triggered the filter."""
        self._filter_active = False
        self.query_one("#filter-bar").display = False
        panel = self.query_one(f"#{self._filter_panel_id}")
        if panel:
            text = self.query_one("#filter-input", Input).value
            panel.border_title = (
                f"{panel.BORDER_TITLE}  [dim]/ {text}[/dim]"
                if text
                else panel.BORDER_TITLE
            )
        self.query_one(f"#{self._filter_panel_id}").focus()
        self.refresh_bindings()

    def on_input_changed(self, event: Input.Changed) -> None:
        if not self._filter_active:
            return
        panel = self.query_one(f"#{self._filter_panel_id}")
        if panel and self._cfg:
            panel.set_filter(event.value)
            self._schedule_filter_refresh()

    def _schedule_filter_refresh(self) -> None:
        if self._filter_refresh_timer is not None:
            self._filter_refresh_timer.stop()
        self._filter_refresh_timer = self.set_timer(
            self._FILTER_DEBOUNCE_SEC,
            self._apply_filter_refresh,
            name="filter_refresh",
        )

    def _apply_filter_refresh(self) -> None:
        if not self._filter_active or self._cfg is None:
            return
        bundle = fetch_refresh_bundle()
        self._tmux = bundle.snap
        panel_id = self._filter_panel_id
        if panel_id == "sessions-tree":
            self.query_one(SessionsPanel).refresh_data(
                self._cfg, bundle.snap, bundle.settings
            )
        elif panel_id == "projects-tree":
            self.query_one(ProjectsPanel).refresh_data(
                self._cfg, bundle.snap, bundle.settings
            )

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        if self._filter_refresh_timer is not None:
            self._filter_refresh_timer.stop()
            self._filter_refresh_timer = None
        self._apply_filter_refresh()
        self._dismiss_filter_bar()
