"""Agents panel — pi agents running inside 'agents' windows per session."""

from __future__ import annotations

from dataclasses import dataclass

from textual.widgets import Tree
from textual.widgets._tree import TreeNode

from txs.tmux import AgentInfo, get_agents


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


class AgentsPanel(Tree):
    """Tree widget showing pi agents grouped by session."""

    BORDER_TITLE = "Agents"

    def __init__(self) -> None:
        super().__init__("Agents", id="agents-tree")
        self.show_root = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_data(self) -> None:
        """Rebuild the tree from live tmux agent state."""
        selected_pane_id = self._selected_pane_id()
        expanded = self._get_expanded_sessions()

        self.clear()

        agents = get_agents()
        by_session: dict[str, list[AgentInfo]] = {}
        for a in agents:
            by_session.setdefault(a.session, []).append(a)

        for session, session_agents in sorted(by_session.items()):
            session_label = f"[bold]{session}[/bold]"
            node = self.root.add(
                session_label,
                data=AgentNode(session=session),
                expand=session in expanded or not expanded,
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

        self._restore_expanded(expanded)
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

    def _get_expanded_sessions(self) -> set[str]:
        expanded: set[str] = set()

        def _walk(node: TreeNode) -> None:
            if node.is_expanded and isinstance(node.data, AgentNode):
                expanded.add(node.data.session)
            for child in node.children:
                _walk(child)

        _walk(self.root)
        return expanded

    def _restore_expanded(self, expanded: set[str]) -> None:
        def _walk(node: TreeNode) -> None:
            if isinstance(node.data, AgentNode) and node.data.session in expanded:
                node.expand()
            for child in node.children:
                _walk(child)

        _walk(self.root)

    def _restore_selection(self, pane_id: str) -> None:
        if not pane_id:
            return

        def _walk(node: TreeNode) -> bool:
            d = node.data
            if isinstance(d, AgentNode) and d.pane_id == pane_id:
                self.move_cursor(node)
                return True
            for child in node.children:
                if _walk(child):
                    return True
            return False

        _walk(self.root)
