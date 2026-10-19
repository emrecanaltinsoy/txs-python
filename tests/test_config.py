"""Tests for config.py — mirrors the bash test suite's config-parser tests."""

from pathlib import Path

import pytest

from txs.config import (
    ProjectConfig,
    expand_path,
    find_project_for_session,
    get_project_prop,
    get_txs_setting,
    is_explicit_project_path,
    parse_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def cfg(content: str, tmp_path: Path) -> ProjectConfig:
    """Write content to a temp projects.conf and parse it."""
    p = tmp_path / "projects.conf"
    p.write_text(content)
    return parse_config(p)


# ---------------------------------------------------------------------------
# Basic parsing
# ---------------------------------------------------------------------------


class TestBasicParsing:
    CONF = """
[DEFAULT]
on_create = echo default

[myproject]
path = ~/projects/test
session_name = test-session
on_create = nvim .

[another]
path = /tmp/another
"""

    def test_project_count(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        assert len(c.projects) == 2

    def test_project_order(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        assert [p.name for p in c.projects] == ["myproject", "another"]

    def test_path(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        assert get_project_prop(c, "myproject", "path") == "~/projects/test"

    def test_session_name(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        assert get_project_prop(c, "myproject", "session_name") == "test-session"

    def test_on_create(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        assert get_project_prop(c, "myproject", "on_create") == "nvim ."

    def test_default_on_create(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        assert c.default_on_create == "echo default"

    def test_fallback_on_create(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        assert get_project_prop(c, "another", "on_create") == "echo default"

    def test_session_name_defaults_to_section(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        assert get_project_prop(c, "another", "session_name") == "another"


# ---------------------------------------------------------------------------
# Multiline on_create
# ---------------------------------------------------------------------------


class TestMultilineOnCreate:
    CONF = """
[multi]
path = ~/multi
on_create = tmux split-window -v
    nvim .
"""

    def test_first_line_preserved(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        oc = get_project_prop(c, "multi", "on_create")
        assert "tmux split-window -v" in oc

    def test_continuation_appended(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        oc = get_project_prop(c, "multi", "on_create")
        assert "nvim ." in oc

    def test_lines_separated_by_newline(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        oc = get_project_prop(c, "multi", "on_create")
        lines = [line for line in oc.splitlines() if line.strip()]
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# Session name sanitisation (dots/colons → underscores)
# ---------------------------------------------------------------------------


class TestSessionNameSanitisation:
    def test_dot_replaced(self, tmp_path):
        c = cfg("[proj]\npath = /tmp/p\nsession_name = foo.bar\n", tmp_path)
        assert get_project_prop(c, "proj", "session_name") == "foo_bar"

    def test_colon_replaced(self, tmp_path):
        c = cfg("[proj]\npath = /tmp/p\nsession_name = foo:bar\n", tmp_path)
        assert get_project_prop(c, "proj", "session_name") == "foo_bar"


# ---------------------------------------------------------------------------
# expand_path
# ---------------------------------------------------------------------------


class TestExpandPath:
    def test_tilde_expanded(self):
        result = expand_path("~/foo/bar")
        assert result.endswith("/foo/bar")
        assert not result.startswith("~")

    def test_absolute_unchanged(self):
        assert expand_path("/tmp/x") == "/tmp/x"

    def test_relative_unchanged(self):
        assert expand_path("foo/bar") == "foo/bar"


# ---------------------------------------------------------------------------
# find_project_for_session
# ---------------------------------------------------------------------------


class TestFindProjectForSession:
    CONF = """
[myproject]
path = ~/projects/test
session_name = test-session
"""

    def test_found(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        assert find_project_for_session(c, "test-session") == "myproject"

    def test_not_found(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        assert find_project_for_session(c, "nonexistent") is None


# ---------------------------------------------------------------------------
# is_explicit_project_path
# ---------------------------------------------------------------------------


class TestIsExplicitProjectPath:
    def test_match(self, tmp_path):
        c = cfg(f"[p]\npath = {tmp_path}\n", tmp_path)
        assert is_explicit_project_path(c, str(tmp_path))

    def test_no_match(self, tmp_path):
        c = cfg(f"[p]\npath = {tmp_path}\n", tmp_path)
        assert not is_explicit_project_path(c, "/some/other/path")

    def test_depth_project_excluded(self, tmp_path):
        c = cfg(f"[p]\npath = {tmp_path}\nmax_depth = 2\n", tmp_path)
        assert not is_explicit_project_path(c, str(tmp_path))


# ---------------------------------------------------------------------------
# get_txs_setting
# ---------------------------------------------------------------------------


class TestGetTxsSetting:
    def test_reads_value(self, tmp_path):
        sf = tmp_path / "config"
        sf.write_text("auto_add_clone = true\n")
        assert get_txs_setting("auto_add_clone", sf) == "true"

    def test_reads_value_with_spaces(self, tmp_path):
        sf = tmp_path / "config"
        sf.write_text("some_other = hello world\n")
        assert get_txs_setting("some_other", sf) == "hello world"

    def test_missing_key_returns_empty(self, tmp_path):
        sf = tmp_path / "config"
        sf.write_text("auto_add_clone = true\n")
        assert get_txs_setting("nonexistent", sf) == ""

    def test_missing_file_returns_empty(self, tmp_path):
        assert get_txs_setting("auto_add_clone", tmp_path / "nonexistent") == ""

    def test_ignores_comments(self, tmp_path):
        sf = tmp_path / "config"
        sf.write_text("# comment\nauto_add_clone = true\n")
        assert get_txs_setting("auto_add_clone", sf) == "true"

    def test_inline_comment_stripped(self, tmp_path):
        sf = tmp_path / "config"
        sf.write_text("fzf_height = 80%  # custom\n")
        assert get_txs_setting("fzf_height", sf) == "80%"

    def test_fzf_height_default(self, tmp_path):
        result = get_txs_setting("fzf_height", tmp_path / "nonexistent") or "50%"
        assert result == "50%"


# ---------------------------------------------------------------------------
# Missing config file raises SystemExit
# ---------------------------------------------------------------------------


def test_missing_config_raises(tmp_path):
    with pytest.raises(SystemExit):
        parse_config(tmp_path / "no_such_file.conf")
