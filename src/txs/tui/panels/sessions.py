"""Sessions panel — active tmux sessions (worktrees included as sessions)."""

from __future__ import annotations

from dataclasses import dataclass

from txs.config import ProjectConfig, TuiSettingsView, build_depth_index
from txs.tmux import TmuxSnapshot
from txs.tui.panels.base import TxsTreePanel


@dataclass
class SessionNode:
    """Data attached to each tree node."""

    session: str
    is_leaf: bool = True  # fzf picker and tree selection look for this


class SessionsPanel(TxsTreePanel):
    """Flat list of active tmux sessions with their window names."""

    BORDER_TITLE = "Sessions"
    BINDING_GROUP_TITLE = "Sessions"

    def __init__(self) -> None:
        super().__init__("Sessions", id="sessions-tree")
        self.show_root = False
        self._filter = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_data(
        self, cfg: ProjectConfig, snap: TmuxSnapshot, settings: TuiSettingsView
    ) -> None:
        """Rebuild the list from live tmux state."""
        selected_label = self._selected_label()
        expanded = self._collect_expanded_keys(SessionNode, lambda d: d.session)

        self.clear()
        build_depth_index(cfg)

        for session in snap.sessions:
            if self._filter and not self.subsequence_match(self._filter, session):
                continue
            self._add_session(session, snap)

        self._apply_expansion_state(expanded, default_expanded=settings.trees_expanded)
        self._restore_selection(selected_label)

    def set_filter(self, text: str) -> None:
        self._filter = text

    def _restore_expanded(self, expanded: set[str]) -> None:
        self._restore_expanded_keys(expanded, SessionNode, lambda d: d.session)

    def selected_node_data(self) -> SessionNode | None:
        if self.cursor_node is None:
            return None
        return (
            self.cursor_node.data
            if isinstance(self.cursor_node.data, SessionNode)
            else None
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add_session(self, session: str, snap: TmuxSnapshot) -> None:
        from rich.markup import escape

        windows = escape(f"[{snap.windows_label(session)}]")
        label = f"[bold green]* {session}[/bold green]  [dim]{windows}[/dim]"
        self.root.add_leaf(label, data=SessionNode(session=session))

    def _selected_label(self) -> str:
        if self.cursor_node and self.cursor_node.data:
            d = self.cursor_node.data
            if isinstance(d, SessionNode):
                return d.session
        return ""

    def _restore_selection(self, label: str) -> None:
        self._restore_cursor_by_key(label, SessionNode, lambda d: d.session)
