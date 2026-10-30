"""Shared tree panel behavior for the TUI."""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar, TypeVar

from textual.binding import Binding, BindingType
from textual.widgets import Tree
from textual.widgets._tree import TreeNode

NodeDataT = TypeVar("NodeDataT")

# Textual's shift+space toggle is sibling-only and unreliable in some terminals.
_TREE_BINDINGS = [
    b for b in Tree.BINDINGS if not (isinstance(b, Binding) and b.key == "shift+space")
]


class TxsTreePanel(Tree):
    """Tree with expand/collapse-all and startup expansion from settings."""

    BINDING_GROUP_TITLE = "Tree"

    BINDINGS: ClassVar[list[BindingType]] = [
        *_TREE_BINDINGS,
        Binding("-", "collapse_all_branches", "Collapse all", show=False),
        Binding("=", "expand_all_branches", "Expand all", show=False),
        Binding("+", "expand_all_branches", show=False),
    ]

    def expand_all_branches(self) -> None:
        for child in self.root.children:
            if child.allow_expand:
                child.expand_all()

    def collapse_all_branches(self) -> None:
        for child in self.root.children:
            if child.allow_expand:
                child.collapse_all()

    def action_expand_all_branches(self) -> None:
        self.expand_all_branches()

    def action_collapse_all_branches(self) -> None:
        self.collapse_all_branches()

    def _apply_expansion_state(
        self, expanded: set[str], *, default_expanded: bool
    ) -> None:
        if expanded:
            self._restore_expanded(expanded)
        elif default_expanded:
            self.expand_all_branches()

    @staticmethod
    def subsequence_match(query: str, text: str) -> bool:
        """Subsequence match — fzf-style. 'xy' matches 'xyz'."""
        if not query:
            return True
        it = iter(text.lower())
        return all(c in it for c in query.lower())

    def leaf_nodes(self) -> list[TreeNode]:
        """Selectable leaves (data.is_leaf), in tree order, including collapsed ones."""
        leaves: list[TreeNode] = []

        def _walk(node: TreeNode) -> None:
            for child in node.children:
                if getattr(child.data, "is_leaf", False):
                    leaves.append(child)
                _walk(child)

        _walk(self.root)
        return leaves

    @staticmethod
    def leaf_label(node: TreeNode) -> str:
        """Plain 'parent › leaf' text for the fzf picker."""
        leaf = node.label.plain if hasattr(node.label, "plain") else str(node.label)
        parent = node.parent
        if parent is None or parent.label is None:
            return leaf.strip()
        parent_text = (
            parent.label.plain if hasattr(parent.label, "plain") else str(parent.label)
        )
        return f"{parent_text.strip()} › {leaf.strip()}"

    def reveal_node(self, node: TreeNode) -> None:
        """Expand ancestors of ``node`` and move the cursor onto it."""
        parent = node.parent
        while parent is not None:
            parent.expand()
            parent = parent.parent
        # Expanding leaves node._line stale until the visible lines are rebuilt;
        # reading last_line forces that rebuild before the cursor moves.
        _ = self.last_line
        self.move_cursor(node)

    def _collect_expanded_keys(
        self,
        node_type: type[NodeDataT],
        key_of: Callable[[NodeDataT], str | None],
    ) -> set[str]:
        expanded: set[str] = set()

        def _walk(node: TreeNode) -> None:
            data = node.data
            if node.is_expanded and isinstance(data, node_type):
                key = key_of(data)
                if key:
                    expanded.add(key)
            for child in node.children:
                _walk(child)

        _walk(self.root)
        return expanded

    def _restore_expanded_keys(
        self,
        expanded: set[str],
        node_type: type[NodeDataT],
        key_of: Callable[[NodeDataT], str | None],
    ) -> None:
        def _walk(node: TreeNode) -> None:
            data = node.data
            if isinstance(data, node_type):
                key = key_of(data)
                if key and key in expanded:
                    node.expand()
            for child in node.children:
                _walk(child)

        _walk(self.root)

    def _restore_cursor_by_key(
        self,
        key: str,
        node_type: type[NodeDataT],
        key_of: Callable[[NodeDataT], str | None],
    ) -> None:
        if not key:
            return

        def _walk(node: TreeNode) -> bool:
            data = node.data
            if isinstance(data, node_type) and key_of(data) == key:
                self.move_cursor(node)
                return True
            for child in node.children:
                if _walk(child):
                    return True
            return False

        _walk(self.root)
