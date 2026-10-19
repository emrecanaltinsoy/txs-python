"""Projects panel — all configured projects with active/inactive status."""

from __future__ import annotations

import os
from dataclasses import dataclass

from textual.widgets import Tree
from textual.widgets._tree import TreeNode

from txs.config import (
    ProjectConfig,
    build_depth_index,
    expand_path,
    find_depth_owner,
    get_project_prop,
    is_explicit_project_path,
)
from txs.git import get_depth_projects, get_project_worktrees, is_bare_repo
from txs.tmux import get_active_sessions


@dataclass
class ProjectNode:
    """Data attached to each tree node."""
    project: str            # config section name / owning depth project
    path: str               # resolved absolute path
    session_name: str = ""  # for leaf nodes that map to a session
    wt_path: str = ""       # for worktree leaf nodes
    is_leaf: bool = False


class ProjectsPanel(Tree):
    """Tree widget showing all configured projects."""

    BORDER_TITLE = "Projects"

    def __init__(self) -> None:
        super().__init__("Projects", id="projects-tree")
        self.show_root = False
        self._filter = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_data(self, cfg: ProjectConfig) -> None:
        """Rebuild the tree from config + live session state."""
        selected_label = self._selected_label()
        expanded = self._get_expanded_keys()

        self.clear()
        build_depth_index(cfg)
        active_sessions = set(get_active_sessions())

        for proj in cfg.projects:
            self._add_project(proj.name, cfg, active_sessions)

        self._restore_expanded(expanded)
        # Auto-expand parents that have filter matches
        if self._filter:
            self._expand_matching_parents()
        self._restore_selection(selected_label)

    def set_filter(self, text: str) -> None:
        self._filter = text

    @staticmethod
    def _matches(query: str, text: str) -> bool:
        """Subsequence match — fzf-style. 'xy' matches 'xyz'."""
        if not query:
            return True
        it = iter(text.lower())
        return all(c in it for c in query.lower())

    def selected_node_data(self) -> ProjectNode | None:
        if self.cursor_node is None:
            return None
        return self.cursor_node.data if isinstance(self.cursor_node.data, ProjectNode) else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add_project(
        self, proj_name: str, cfg: ProjectConfig, active_sessions: set[str]
    ) -> None:
        path = expand_path(get_project_prop(cfg, proj_name, "path"))
        session_name = get_project_prop(cfg, proj_name, "session_name")
        depth = int(get_project_prop(cfg, proj_name, "max_depth") or "0")

        if depth > 0:
            self._add_depth_project(proj_name, path, depth, cfg, active_sessions)
            return

        if not os.path.isdir(path):
            return

        if is_bare_repo(path):
            self._add_bare_project(proj_name, path, session_name, cfg, active_sessions)
            return

        # Regular project — leaf; skip if filter doesn’t match
        if self._filter and not self._matches(self._filter, proj_name):
            return

        active = session_name in active_sessions
        label = self._project_label(proj_name, active)
        self.root.add_leaf(
            label,
            data=ProjectNode(
                project=proj_name,
                path=path,
                session_name=session_name,
                is_leaf=True,
            ),
        )

    def _add_bare_project(
        self,
        proj_name: str,
        path: str,
        session_name: str,
        cfg: ProjectConfig,
        active_sessions: set[str],
    ) -> None:
        active = session_name in active_sessions
        label = self._project_label(proj_name, active)
        node = self.root.add(
            label,
            data=ProjectNode(project=proj_name, path=path, session_name=session_name),
            expand=False,
        )
        children_added = 0
        for wt, wt_name in sorted(get_project_worktrees(path), key=lambda x: x[1]):
            if self._filter and not self._matches(self._filter, wt_name) and not self._matches(self._filter, proj_name):
                continue
            node.add_leaf(
                f"  [dim]{wt_name}[/dim]",
                data=ProjectNode(
                    project=proj_name,
                    path=path,
                    session_name=session_name,
                    wt_path=wt,
                    is_leaf=True,
                ),
            )
            children_added += 1
        if self._filter and children_added == 0:
            node.remove()

    def _add_depth_project(
        self,
        proj_name: str,
        root_path: str,
        depth: int,
        cfg: ProjectConfig,
        active_sessions: set[str],
    ) -> None:
        label = f"[cyan]{proj_name}[/cyan]  [dim][depth={depth}][/dim]"
        node = self.root.add(
            label,
            data=ProjectNode(project=proj_name, path=root_path),
            expand=False,
        )
        for dp_path, dp_name in get_depth_projects(root_path, depth):
            if is_explicit_project_path(cfg, dp_path):
                continue
            owner = find_depth_owner(cfg, dp_name)
            if owner is None or owner[0] != proj_name:
                continue
            if self._filter and not self._matches(self._filter, dp_name) and not self._matches(self._filter, proj_name):
                continue

            active = dp_name in active_sessions
            child_label = f"  {self._session_status(active)}{dp_name}"

            if is_bare_repo(dp_path):
                child_node = node.add(
                    child_label,
                    data=ProjectNode(
                        project=proj_name, path=dp_path, session_name=dp_name
                    ),
                    expand=False,
                )
                for wt, wt_name in sorted(
                    get_project_worktrees(dp_path), key=lambda x: x[1]
                ):
                    child_node.add_leaf(
                        f"    [dim]{wt_name}[/dim]",
                        data=ProjectNode(
                            project=proj_name,
                            path=dp_path,
                            session_name=dp_name,
                            wt_path=wt,
                            is_leaf=True,
                        ),
                    )
            else:
                node.add_leaf(
                    child_label,
                    data=ProjectNode(
                        project=proj_name,
                        path=dp_path,
                        session_name=dp_name,
                        is_leaf=True,
                    ),
                )

    @staticmethod
    def _session_status(active: bool) -> str:
        return "[green]* [/green]" if active else "[dim]  [/dim]"

    @staticmethod
    def _project_label(name: str, active: bool) -> str:
        status = "[green]* [/green]" if active else "[dim]  [/dim]"
        return f"{status}[cyan]{name}[/cyan]"

    def _expand_matching_parents(self) -> None:
        """Expand any parent node that has visible children after filtering."""
        def _walk(node: TreeNode) -> None:
            if node.children:
                has_leaf = any(not c.children for c in node.children)
                if has_leaf:
                    node.expand()
                for child in node.children:
                    _walk(child)
        _walk(self.root)

    def _get_expanded_keys(self) -> set[str]:
        expanded: set[str] = set()
        def _walk(node: TreeNode) -> None:
            if node.is_expanded and isinstance(node.data, ProjectNode):
                expanded.add(node.data.project + "|" + node.data.path)
            for child in node.children:
                _walk(child)
        _walk(self.root)
        return expanded

    def _restore_expanded(self, expanded: set[str]) -> None:
        def _walk(node: TreeNode) -> None:
            if isinstance(node.data, ProjectNode):
                key = node.data.project + "|" + node.data.path
                if key in expanded:
                    node.expand()
            for child in node.children:
                _walk(child)
        _walk(self.root)

    def _selected_label(self) -> str:
        if self.cursor_node and self.cursor_node.data:
            d = self.cursor_node.data
            if isinstance(d, ProjectNode):
                return d.wt_path or d.session_name or d.project
        return ""

    def _restore_selection(self, label: str) -> None:
        if not label:
            return
        def _walk(node: TreeNode) -> bool:
            d = node.data
            if isinstance(d, ProjectNode):
                if (d.wt_path or d.session_name or d.project) == label:
                    self.move_cursor(node)
                    return True
            for child in node.children:
                if _walk(child):
                    return True
            return False
        _walk(self.root)
