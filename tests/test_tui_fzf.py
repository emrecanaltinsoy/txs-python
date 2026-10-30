"""Tests for the TUI fzf picker helpers and tree-panel leaf selection."""

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace

from rich.text import Text
from textual.app import App

from txs.tui import app as tui_app
from txs.tui.fzf import fzf_available, plain_label, run_fzf_pick
from txs.tui.panels.base import TxsTreePanel


class _Proc:
    def __init__(self, returncode: int, stdout: str) -> None:
        self.returncode = returncode
        self.stdout = stdout


def _fake_fzf(monkeypatch, returncode: int, stdout: str) -> list[str]:
    """Patch fzf's subprocess call; return the stdin it was given."""
    seen: list[str] = []

    def fake_run(cmd, input, **kwargs):
        seen.append(input)
        return _Proc(returncode, stdout)

    monkeypatch.setattr("txs.tui.fzf.subprocess.run", fake_run)
    return seen


class TestRunFzfPick:
    def test_returns_index_of_selected_line(self, monkeypatch):
        seen = _fake_fzf(monkeypatch, 0, "2\tproj \u203a proj.main\n")
        assert run_fzf_pick(["a", "b", "c"], "h", "p") == 2
        assert seen == ["0\ta\n1\tb\n2\tc"]

    def test_cancel_returns_none(self, monkeypatch):
        _fake_fzf(monkeypatch, 130, "")
        assert run_fzf_pick(["a"], "h", "p") is None

    def test_empty_output_returns_none(self, monkeypatch):
        _fake_fzf(monkeypatch, 0, "")
        assert run_fzf_pick(["a"], "h", "p") is None

    def test_no_labels_skips_fzf(self, monkeypatch):
        seen = _fake_fzf(monkeypatch, 0, "0\tx\n")
        assert run_fzf_pick([], "h", "p") is None
        assert seen == []


class TestFzfAvailable:
    def test_missing_fzf(self, monkeypatch):
        monkeypatch.setattr("txs.tui.fzf.shutil.which", lambda _name: None)
        assert fzf_available() is False

    def test_present_fzf(self, monkeypatch):
        monkeypatch.setattr("txs.tui.fzf.shutil.which", lambda _name: "/usr/bin/fzf")
        assert fzf_available() is True


def test_plain_label_strips_markup():
    assert plain_label("[bold]proj[/bold]  [dim]idle[/dim]") == "proj  idle"


@dataclass
class _Item:
    name: str = ""
    is_leaf: bool = False


class _Panel(TxsTreePanel):
    def on_mount(self) -> None:
        group = self.root.add("[bold]s1[/bold]", data=_Item("s1"), expand=False)
        group.add_leaf("main", data=_Item("main", is_leaf=True))
        group.add_leaf("feat", data=_Item("feat", is_leaf=True))
        other = self.root.add("[bold]s2[/bold]", data=_Item("s2"), expand=False)
        other.add_leaf("hotfix", data=_Item("hotfix", is_leaf=True))


def _with_panel(check) -> None:
    class Host(App):
        def compose(self):
            yield _Panel("root")

    async def run() -> None:
        async with Host().run_test() as pilot:
            await pilot.pause()
            check(pilot.app.query_one(_Panel))

    asyncio.run(run())


def test_leaf_nodes_include_collapsed_branches_in_tree_order():
    def check(panel: _Panel) -> None:
        names = [n.data.name for n in panel.leaf_nodes()]
        assert names == ["main", "feat", "hotfix"]

    _with_panel(check)


def test_leaf_label_prefixes_parent_name():
    def check(panel: _Panel) -> None:
        labels = [panel.leaf_label(n) for n in panel.leaf_nodes()]
        assert labels == ["s1 \u203a main", "s1 \u203a feat", "s2 \u203a hotfix"]

    _with_panel(check)


def test_reveal_node_expands_parent_and_moves_cursor():
    def check(panel: _Panel) -> None:
        target = panel.leaf_nodes()[2]
        panel.reveal_node(target)
        assert target.parent.is_expanded
        assert panel.cursor_node is target

    _with_panel(check)


# ---------------------------------------------------------------------------
# App-level: the `/` key (headless TxsApp)
# ---------------------------------------------------------------------------


def _press_slash(panel_id: str, monkeypatch, *, fzf: bool, pick=None):
    """Focus a panel in headless TxsApp, press '/', return (app, filter_bar_shown)."""
    monkeypatch.setattr(tui_app, "fzf_available", lambda: fzf)
    # Fixed leaves so the result doesn't depend on live tmux sessions.
    fake_leaf = SimpleNamespace(label=Text("s1 \u203a main"), parent=None)
    monkeypatch.setattr(TxsTreePanel, "leaf_nodes", lambda self: [fake_leaf])
    if pick is not None:
        monkeypatch.setattr(tui_app, "run_fzf_pick", pick)
    result: dict = {}

    async def run() -> None:
        app = tui_app.TxsApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one(f"#{panel_id}").focus()
            await pilot.pause()
            await pilot.press("slash")
            await pilot.pause()
            result["shown"] = app.query_one("#filter-bar").display
            result["exited"] = app.return_value is not None
            result["app"] = app

    asyncio.run(run())
    return result


class TestSlashKey:
    def test_without_fzf_sessions_uses_inline_filter(self, monkeypatch):
        r = _press_slash("sessions-tree", monkeypatch, fzf=False)
        assert r["shown"] is True

    def test_without_fzf_agents_has_no_filter(self, monkeypatch):
        r = _press_slash("agents-tree", monkeypatch, fzf=False)
        assert r["shown"] is False

    def test_fzf_present_but_suspend_unsupported_falls_back(self, monkeypatch):
        # Headless terminals can't suspend, so the inline filter takes over.
        r = _press_slash("sessions-tree", monkeypatch, fzf=True)
        assert r["shown"] is True

    def test_fzf_cancel_returns_to_panel_without_exit(self, monkeypatch):
        @contextmanager
        def fake_suspend(self):
            yield

        monkeypatch.setattr(tui_app.TxsApp, "suspend", fake_suspend)
        r = _press_slash(
            "sessions-tree", monkeypatch, fzf=True, pick=lambda *a, **k: None
        )
        assert r["shown"] is False
        assert r["exited"] is False
