"""Shared tree panel behavior for the TUI."""

from __future__ import annotations

from typing import ClassVar

from textual.binding import Binding, BindingType
from textual.widgets import Tree

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
