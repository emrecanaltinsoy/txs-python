"""Sessions panel — active tmux sessions with worktree sub-items."""

from __future__ import annotations

from dataclasses import dataclass

from textual.widgets import Tree
from textual.widgets._tree import TreeNode

from txs.config import (
    ProjectConfig,
    build_depth_index,
    expand_path,
    find_depth_owner,
    find_project_for_session,
    get_project_prop,
)
from txs.git import get_project_worktrees, is_bare_repo
from txs.tmux import (
    fetch_session_windows,
    find_window_by_path,
    get_active_sessions,
    get_session_windows,
)


@dataclass
class SessionNode:
    """Data attached to each tree node."""
    session: str
    wt_path: str = ""       # non-empty for worktree child nodes
    is_leaf: bool = False   # True for nodes you can attach to directly


class SessionsPanel(Tree):
    """Tree widget showing active tmux sessions."""

    BORDER_TITLE = "Sessions"

    def __init__(self) -> None:
        super().__init__("Sessions", id="sessions-tree")
        self.show_root = False
        self._filter = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_data(self, cfg: ProjectConfig) -> None:
        """Rebuild the tree from live tmux state."""
        selected_label = self._selected_label()
        expanded = self._get_expanded_keys()

        self.clear()
        build_depth_index(cfg)
        fetch_session_windows()

        sessions = get_active_sessions()
        for session in sessions:
            if self._filter and not self._matches(self._filter, session):
                # Still add if a worktree child matches
                if not self._session_has_match(session, cfg):
                    continue
            self._add_session(session, cfg)

        self._restore_expanded(expanded)
        self._restore_selection(selected_label)

    def set_filter(self, text: str) -> None:
        self._filter = text

    @staticmethod
    def _matches(query: str, text: str) -> bool:
        """Subsequence match — fzf-style."""
        if not query:
            return True
        it = iter(text.lower())
        return all(c in it for c in query.lower())

    def selected_node_data(self) -> SessionNode | None:
        if self.cursor_node is None:
            return None
        return self.cursor_node.data if isinstance(self.cursor_node.data, SessionNode) else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add_session(self, session: str, cfg: ProjectConfig) -> None:
        proj = find_project_for_session(cfg, session)
        depth_info = find_depth_owner(cfg, session)

        windows = get_session_windows(session)
        label = f"[bold green]* {session}[/bold green]  [dim][{windows}][/dim]"

        # Bare repo session → expandable with worktree children
        if proj:
            path = expand_path(get_project_prop(cfg, proj, "path"))
            if is_bare_repo(path):
                node = self.root.add(
                    label,
                    data=SessionNode(session=session),
                    expand=True,
                )
                self._add_worktree_children(node, session, path)
                return

        # Depth-discovered bare repo session
        if depth_info:
            _, dp_path = depth_info
            if dp_path and is_bare_repo(dp_path):
                node = self.root.add(
                    label,
                    data=SessionNode(session=session),
                    expand=True,
                )
                self._add_worktree_children(node, session, dp_path)
                return

        # Regular session — leaf node
        self.root.add_leaf(
            label,
            data=SessionNode(session=session, is_leaf=True),
        )

    def _session_has_match(self, session: str, cfg: ProjectConfig) -> bool:
        """True if any worktree of this session matches the current filter."""
        proj = find_project_for_session(cfg, session)
        if not proj:
            return False
        path = expand_path(get_project_prop(cfg, proj, "path"))
        if not is_bare_repo(path):
            return False
        return any(
            self._matches(self._filter, wt_name)
            for _, wt_name in get_project_worktrees(path)
        )

    def _add_worktree_children(
        self, node: TreeNode, session: str, path: str
    ) -> None:
        for wt, wt_name in sorted(get_project_worktrees(path), key=lambda x: x[1]):
            if self._filter and not self._matches(self._filter, wt_name) and not self._matches(self._filter, session):
                continue
            matched = find_window_by_path(session, wt)
            if matched:
                label = f"[green]  {wt_name}[/green]"
            else:
                label = f"[dim]  {wt_name}[/dim]"
            node.add_leaf(
                label,
                data=SessionNode(session=session, wt_path=wt, is_leaf=True),
            )

    def _get_expanded_keys(self) -> set[str]:
        expanded: set[str] = set()
        def _walk(node: TreeNode) -> None:
            if node.is_expanded and isinstance(node.data, SessionNode):
                expanded.add(node.data.session)
            for child in node.children:
                _walk(child)
        _walk(self.root)
        return expanded

    def _restore_expanded(self, expanded: set[str]) -> None:
        def _walk(node: TreeNode) -> None:
            if isinstance(node.data, SessionNode) and node.data.session in expanded:
                node.expand()
            for child in node.children:
                _walk(child)
        _walk(self.root)

    def _selected_label(self) -> str:
        if self.cursor_node and self.cursor_node.data:
            d = self.cursor_node.data
            if isinstance(d, SessionNode):
                return d.wt_path or d.session
        return ""

    def _restore_selection(self, label: str) -> None:
        if not label:
            return
        # Walk tree nodes to find a match
        def _walk(node: TreeNode) -> bool:
            d = node.data
            if isinstance(d, SessionNode):
                if (d.wt_path or d.session) == label:
                    self.move_cursor(node)
                    return True
            for child in node.children:
                if _walk(child):
                    return True
            return False
        _walk(self.root)
