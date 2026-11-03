"""Worktree sessions: naming, truncation settings, and attach behaviour."""

import pytest

from txs import config, tmux


@pytest.fixture
def settings(monkeypatch):
    """Return a dict-backed stand-in for the txs settings file."""
    values: dict[str, str] = {}
    monkeypatch.setattr(
        config, "get_txs_setting", lambda key, *a, **k: values.get(key, "")
    )
    return values


class TestWorktreeSessionName:
    def test_default_is_base_slash_worktree(self, settings):
        assert tmux.worktree_session_name("proj", "/x/feature") == "proj/feature"

    def test_default_truncates_to_24(self, settings):
        long_name = "a" * 40
        name = tmux.worktree_session_name("proj", f"/x/{long_name}")
        assert name == "proj/" + "a" * 24

    def test_truncation_length_from_settings(self, settings):
        settings["worktree_session_max_len"] = "10"
        assert tmux.worktree_session_name("p", "/x/abcdefghijklmnop") == "p/abcdefghij"

    def test_truncation_can_be_disabled(self, settings):
        settings["worktree_session_truncate"] = "false"
        long_name = "b" * 40
        assert tmux.worktree_session_name("p", f"/x/{long_name}") == f"p/{long_name}"

    def test_invalid_length_falls_back_to_default(self, settings):
        settings["worktree_session_max_len"] = "nope"
        assert tmux.worktree_session_name("p", "/x/" + "c" * 40) == "p/" + "c" * 24

    def test_dots_and_colons_are_sanitized(self, settings):
        assert tmux.worktree_session_name("my.proj", "/x/a:b") == "my_proj/a_b"


class TestAttachWorktree:
    def _record(self, monkeypatch, exists: bool):
        calls: list[list[str]] = []
        attached: list[str] = []
        monkeypatch.setattr(tmux, "session_exists", lambda _name: exists)
        monkeypatch.setattr(
            tmux.subprocess,
            "run",
            lambda args, **kwargs: calls.append(args),
        )
        monkeypatch.setattr(tmux, "attach_or_switch", attached.append)
        return calls, attached

    def test_creates_session_at_worktree_and_runs_on_create(
        self, monkeypatch, settings
    ):
        calls, attached = self._record(monkeypatch, exists=False)
        name = tmux.attach_worktree("proj", "/x/feature", "echo hi\n\nls")

        assert name == "proj/feature"
        assert calls[0] == [
            "tmux",
            "new-session",
            "-d",
            "-s",
            "proj/feature",
            "-c",
            "/x/feature",
        ]
        sent = [c[-2] for c in calls[1:]]
        assert sent == ["echo hi", "ls"]
        assert attached == ["proj/feature"]

    def test_existing_session_is_only_attached(self, monkeypatch, settings):
        calls, attached = self._record(monkeypatch, exists=True)
        tmux.attach_worktree("proj", "/x/feature", "echo hi")

        assert calls == []
        assert attached == ["proj/feature"]
