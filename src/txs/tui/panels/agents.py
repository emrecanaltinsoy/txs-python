"""Agents panel — pi agents running inside 'agents' windows per session."""

from __future__ import annotations

from dataclasses import dataclass

from txs.config import TuiSettingsView
from txs.tmux import AgentInfo, TmuxSnapshot
from txs.tui.panels.base import TxsTreePanel


@dataclass
class AgentNode:
    """Data attached to each tree node."""

    session: str
    pane_id: str = ""
    pane_index: str = ""
    title: str = ""
    command: str = ""
    is_leaf: bool = False

    @property
    def is_running(self) -> bool:
        return self.command == "pi"


class AgentsPanel(TxsTreePanel):
    """Tree widget showing pi agents grouped by session."""

    BORDER_TITLE = "Agents"
    BINDING_GROUP_TITLE = "Agents"

    def __init__(self) -> None:
        super().__init__("Agents", id="agents-tree")
        self.show_root = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_data(self, snap: TmuxSnapshot, settings: TuiSettingsView) -> None:
        """Rebuild the tree from live tmux agent state."""
        selected_pane_id = self._selected_pane_id()
        expanded = self._collect_expanded_keys(
            AgentNode,
            lambda d: d.session if not d.is_leaf else None,
        )

        self.clear()

        agents = snap.agents
        by_session: dict[str, list[AgentInfo]] = {}
        for a in agents:
            by_session.setdefault(a.session, []).append(a)

        for session, session_agents in sorted(by_session.items()):
            session_label = f"[bold]{session}[/bold]"
            node = self.root.add(
                session_label,
                data=AgentNode(session=session),
                expand=False,
            )
            for agent in session_agents:
                status = (
                    "[green]running[/green]" if agent.is_running else "[dim]idle[/dim]"
                )
                label = f"  {agent.title}  [dim][pi · {status}][/dim]"
                node.add_leaf(
                    label,
                    data=AgentNode(
                        session=session,
                        pane_id=agent.pane_id,
                        pane_index=agent.pane_index,
                        title=agent.title,
                        command=agent.command,
                        is_leaf=True,
                    ),
                )

        self._apply_expansion_state(expanded, default_expanded=settings.trees_expanded)
        self._restore_selection(selected_pane_id)

    def selected_node_data(self) -> AgentNode | None:
        if self.cursor_node is None:
            return None
        return (
            self.cursor_node.data
            if isinstance(self.cursor_node.data, AgentNode)
            else None
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _selected_pane_id(self) -> str:
        if self.cursor_node and isinstance(self.cursor_node.data, AgentNode):
            return self.cursor_node.data.pane_id
        return ""

    def _restore_expanded(self, expanded: set[str]) -> None:
        self._restore_expanded_keys(
            expanded,
            AgentNode,
            lambda d: d.session if not d.is_leaf else None,
        )

    def _restore_selection(self, pane_id: str) -> None:
        self._restore_cursor_by_key(pane_id, AgentNode, lambda d: d.pane_id or None)
