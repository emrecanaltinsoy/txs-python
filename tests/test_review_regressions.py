"""Regression coverage for worktree paths, session scope, and agent cancellation."""

import asyncio
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from textual.app import App

from txs import commands, config, tmux, ui
from txs.__main__ import _run_tui
from txs.tui.app import LabelInputScreen, TxsApp


@pytest.mark.parametrize("name", ["work tree", "work'tree", "wt;touch marker;#"])
def test_first_bare_attach_treats_worktree_path_as_literal(tmp_path, monkeypatch, name):
    """Treat special characters in worktree paths as literal directory names."""
    worktree = tmp_path / name
    worktree.mkdir()
    calls = []
    with monkeypatch.context() as patch:
        patch.setattr(
            commands, "get_project_worktrees", lambda _: [(str(worktree), name)]
        )
        patch.setattr(commands, "attach_or_switch", lambda _: None)
        patch.setattr(
            commands.subprocess, "run", lambda args, **kwargs: calls.append(args)
        )
        commands._attach_bare_repo("repo", str(tmp_path), "repo", "", name, True)

    cd_command = next(args[-2] for args in calls if args[1] == "send-keys")
    result = subprocess.run(
        ["sh", "-c", f"{cd_command} && pwd"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert Path(result.stdout.strip()) == worktree
    assert not (tmp_path / "marker").exists()


@pytest.mark.parametrize("picker", ["tui", "fzf"])
def test_tui_attaches_configured_bare_worktree(tmp_path, monkeypatch, picker):
    """Both pickers attach the chosen path when worktree basenames collide."""
    worktree = tmp_path / "second" / "repo.main"
    other = tmp_path / "first" / "repo.main"
    worktree.mkdir(parents=True)
    other.mkdir(parents=True)
    conf = tmp_path / "projects.conf"
    conf.write_text(f"[repo]\npath = {tmp_path}\n")
    cfg = config.parse_config(conf)
    opened = Mock()
    monkeypatch.setattr(config, "parse_config", lambda: cfg)
    monkeypatch.setattr(commands, "parse_config", lambda: cfg)
    monkeypatch.setattr(commands, "_ensure_session", lambda *args: "existed")
    monkeypatch.setattr(commands, "is_bare_repo", lambda _: True)
    monkeypatch.setattr(
        commands,
        "get_project_worktrees",
        lambda _: [(str(other), other.name), (str(worktree), worktree.name)],
    )
    monkeypatch.setattr(commands, "open_worktree_in_session", opened)
    monkeypatch.setattr(
        TxsApp,
        "run",
        lambda _: ("attach_project", "repo", str(tmp_path), str(worktree), "repo"),
    )

    if picker == "tui":
        _run_tui()
    else:
        monkeypatch.setattr(ui, "is_bare_repo", lambda _: True)
        ui._handle_selection(
            cfg,
            ui.PickerEntry("+", "", "repo", str(worktree), "", ""),
        )

    opened.assert_called_once_with("repo", str(worktree), "")


@pytest.fixture
def tmux_socket():
    """Provide a short, isolated socket path and remove it after teardown."""
    # macOS pytest paths can exceed the Unix socket filename limit.
    with TemporaryDirectory(prefix="txs-", dir="/tmp") as directory:
        yield str(Path(directory) / "tmux.sock")


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")
def test_window_lookup_searches_all_windows_in_only_requested_session(
    tmp_path, monkeypatch, tmux_socket
):
    """Keep live lookup scoped to one session across all of its windows."""
    original_run = subprocess.run

    def isolated_run(args, **kwargs):
        """Route only tmux commands to the test server."""
        if args[0] == "tmux":
            args = ["tmux", "-S", tmux_socket, *args[1:]]
        return original_run(args, **kwargs)

    target = tmp_path / "target"
    elsewhere = tmp_path / "elsewhere"
    target.mkdir()
    elsewhere.mkdir()
    try:
        isolated_run(
            [
                "tmux",
                "-f",
                "/dev/null",
                "new-session",
                "-d",
                "-s",
                "one",
                "-c",
                str(target),
            ],
            check=True,
        )
        isolated_run(
            ["tmux", "new-session", "-d", "-s", "two", "-c", str(elsewhere)], check=True
        )
        monkeypatch.setattr(tmux.subprocess, "run", isolated_run)
        assert tmux.find_window_by_path("one", str(elsewhere)) is None
        window = isolated_run(
            [
                "tmux",
                "new-window",
                "-d",
                "-t",
                "=one:",
                "-c",
                str(elsewhere),
                "-P",
                "-F",
                "#{window_index}",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert tmux.find_window_by_path("one", str(elsewhere)) == window
    finally:
        isolated_run(["tmux", "kill-server"], capture_output=True, check=False)


@pytest.mark.parametrize(
    "keys,label", [(["escape"], None), (["enter"], ""), (["r", "enter"], "r")]
)
def test_agent_label_cancel_and_submit_are_distinct(monkeypatch, keys, label):
    """Escape cancels, while blank and custom labels continue agent creation."""
    launch = Mock()
    paths = Mock(return_value=[("/repo", "repo")])
    host = SimpleNamespace(_launch=launch)
    monkeypatch.setattr("txs.tui.app.get_session_worktree_paths", paths)

    class Host(App):
        def on_mount(self):
            self.push_screen(
                LabelInputScreen(),
                lambda value: TxsApp._on_label_entered(host, "repo", value),
            )

    async def interact():
        async with Host().run_test() as pilot:
            await pilot.press(*keys)
            await pilot.pause()

    asyncio.run(interact())
    if label is None:
        paths.assert_not_called()
        launch.assert_not_called()
    else:
        launch.assert_called_once_with("repo", label, "/repo")


@pytest.mark.parametrize("destination", ["clone", "nested/clone", "clone/", "absolute"])
def test_clone_bare_keeps_default_worktree_inside_destination(
    tmp_path, monkeypatch, destination
):
    """All destination forms keep the default worktree below the clone root."""
    origin = tmp_path / "origin"
    subprocess.run(["git", "init", "-q", "-b", "main", str(origin)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(origin),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "initial",
        ],
        check=True,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(commands, "get_txs_setting", lambda _: "")
    if destination == "absolute":
        destination = str(tmp_path / "absolute")
    root = Path(destination).resolve()

    commands.cmd_clone_bare(str(origin), destination)

    assert (root / f"{root.name}.main" / ".git").is_file()
    worktrees = subprocess.run(
        ["git", "-C", str(root), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert f"worktree {root / f'{root.name}.main'}\n" in worktrees


@pytest.mark.parametrize("selector", ["repo.main", "full", "missing"])
def test_bare_attach_accepts_cli_names_and_exact_paths(tmp_path, monkeypatch, selector):
    """Keep CLI name selectors and reject paths outside the listed worktrees."""
    worktree = tmp_path / "repo.main"
    opened = Mock()
    monkeypatch.setattr(
        commands, "get_project_worktrees", lambda _: [(str(worktree), worktree.name)]
    )
    monkeypatch.setattr(commands, "open_worktree_in_session", opened)
    if selector == "full":
        selector = str(worktree)
    elif selector == "missing":
        selector = str(tmp_path / "unlisted" / "repo.main")
        with pytest.raises(SystemExit):
            commands._attach_bare_repo(
                "repo", str(tmp_path), "repo", "", selector, False
            )
        opened.assert_not_called()
        return
    commands._attach_bare_repo("repo", str(tmp_path), "repo", "", selector, False)
    opened.assert_called_once_with("repo", str(worktree), "")


@pytest.mark.parametrize(
    "requested,pane,expected",
    [
        ("/repo/", "/repo", "2"),
        ("/repo///", "/repo/src", "2"),
        ("/repo/", "/repository", None),
        ("/", "/repo", "2"),
        ("/", "/", "2"),
        ("/repo", "/repo/src", "2"),
    ],
)
def test_live_and_snapshot_window_lookup_normalize_trailing_slashes(
    monkeypatch, requested, pane, expected
):
    """Reuse existing windows while preserving root and directory boundaries."""
    monkeypatch.setattr(
        tmux.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 0, stdout=f"2|{pane}\n"
        ),
    )
    snap = tmux.TmuxSnapshot(("repo",), {}, [], {"repo": [("2", pane)]})
    assert tmux.find_window_by_path("repo", requested) == expected
    assert snap.window_for_path("repo", requested) == expected
