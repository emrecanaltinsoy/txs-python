"""Tests for config.py — config.toml parsing, settings, migration, and writers."""

import pytest

from txs.config import (
    CONFIG_FILE,
    add_project,
    expand_path,
    find_project_for_session,
    get_project_prop,
    get_txs_setting,
    invalidate_config_cache,
    is_explicit_project_path,
    parse_config,
    project_exists,
    reload_config_if_changed,
    remove_project,
    set_txs_setting,
    setting_bool,
    setting_is_true,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def cfg(content: str, tmp_path):
    """Write content to a temp config.toml and parse it."""
    p = tmp_path / "config.toml"
    p.write_text(content)
    return parse_config(p)


# ---------------------------------------------------------------------------
# Basic parsing
# ---------------------------------------------------------------------------


class TestBasicParsing:
    CONF = """
[defaults]
on_create = "echo default"

[projects.myproject]
path = "~/projects/test"
session_name = "test-session"
on_create = "nvim ."

[projects.another]
path = "/tmp/another"
"""

    def test_project_count(self, tmp_path):
        assert len(cfg(self.CONF, tmp_path).projects) == 2

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
        assert cfg(self.CONF, tmp_path).default_on_create == "echo default"

    def test_fallback_on_create(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        assert get_project_prop(c, "another", "on_create") == "echo default"

    def test_session_name_defaults_to_project_name(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        assert get_project_prop(c, "another", "session_name") == "another"

    def test_dotted_project_name_is_quoted_key(self, tmp_path):
        c = cfg('[projects."emrecanaltinsoy.github.io"]\npath = "/tmp/x"\n', tmp_path)
        assert [p.name for p in c.projects] == ["emrecanaltinsoy.github.io"]


# ---------------------------------------------------------------------------
# Multiline on_create
# ---------------------------------------------------------------------------


class TestMultilineOnCreate:
    CONF = '''
[projects.multi]
path = "~/multi"
on_create = """tmux split-window -v
nvim ."""
'''

    def test_first_line_preserved(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        assert "tmux split-window -v" in get_project_prop(c, "multi", "on_create")

    def test_continuation_appended(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        assert "nvim ." in get_project_prop(c, "multi", "on_create")

    def test_lines_separated_by_newline(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        lines = get_project_prop(c, "multi", "on_create").splitlines()
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# Session name sanitisation (dots/colons → underscores)
# ---------------------------------------------------------------------------


class TestSessionNameSanitisation:
    def test_dot_replaced(self, tmp_path):
        c = cfg(
            '[projects.proj]\npath = "/tmp/p"\nsession_name = "foo.bar"\n', tmp_path
        )
        assert get_project_prop(c, "proj", "session_name") == "foo_bar"

    def test_colon_replaced(self, tmp_path):
        c = cfg(
            '[projects.proj]\npath = "/tmp/p"\nsession_name = "foo:bar"\n', tmp_path
        )
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
# find_project_for_session / is_explicit_project_path
# ---------------------------------------------------------------------------


class TestFindProjectForSession:
    CONF = """
[projects.myproject]
path = "~/projects/test"
session_name = "test-session"
"""

    def test_found(self, tmp_path):
        assert (
            find_project_for_session(cfg(self.CONF, tmp_path), "test-session")
            == "myproject"
        )

    def test_not_found(self, tmp_path):
        assert find_project_for_session(cfg(self.CONF, tmp_path), "nonexistent") is None


class TestIsExplicitProjectPath:
    def test_match(self, tmp_path):
        c = cfg(f'[projects.p]\npath = "{tmp_path}"\n', tmp_path)
        assert is_explicit_project_path(c, str(tmp_path))

    def test_no_match(self, tmp_path):
        c = cfg(f'[projects.p]\npath = "{tmp_path}"\n', tmp_path)
        assert not is_explicit_project_path(c, "/some/other/path")

    def test_depth_project_excluded(self, tmp_path):
        c = cfg(f'[projects.p]\npath = "{tmp_path}"\nmax_depth = 2\n', tmp_path)
        assert not is_explicit_project_path(c, str(tmp_path))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class TestGetTxsSetting:
    def test_reads_string(self, tmp_path):
        sf = tmp_path / "config.toml"
        sf.write_text('[settings]\nfzf_height = "80%"\n')
        assert get_txs_setting("fzf_height", sf) == "80%"

    def test_reads_bool_as_lowercase_string(self, tmp_path):
        sf = tmp_path / "config.toml"
        sf.write_text("[settings]\nauto_add_clone = true\n")
        assert get_txs_setting("auto_add_clone", sf) == "true"

    def test_reads_int_as_string(self, tmp_path):
        sf = tmp_path / "config.toml"
        sf.write_text("[settings]\nworktree_session_max_len = 24\n")
        assert get_txs_setting("worktree_session_max_len", sf) == "24"

    def test_missing_key_returns_empty(self, tmp_path):
        sf = tmp_path / "config.toml"
        sf.write_text("[settings]\nauto_add_clone = true\n")
        assert get_txs_setting("nonexistent", sf) == ""

    def test_missing_file_returns_empty(self, tmp_path):
        assert get_txs_setting("auto_add_clone", tmp_path / "nonexistent.toml") == ""

    def test_ignores_settings_outside_section(self, tmp_path):
        sf = tmp_path / "config.toml"
        sf.write_text(
            '[projects.p]\nfzf_height = "1"\n\n[settings]\nfzf_height = "2"\n'
        )
        assert get_txs_setting("fzf_height", sf) == "2"

    def test_fzf_height_default(self, tmp_path):
        result = get_txs_setting("fzf_height", tmp_path / "nonexistent.toml") or "50%"
        assert result == "50%"


class TestSetTxsSetting:
    def test_updates_existing_key(self, tmp_path):
        sf = tmp_path / "config.toml"
        sf.write_text('[settings]\nauto_add_clone = true\ntui_theme = "textual-dark"\n')
        set_txs_setting("tui_theme", "nord", sf)
        assert get_txs_setting("tui_theme", sf) == "nord"
        assert get_txs_setting("auto_add_clone", sf) == "true"

    def test_appends_missing_key_to_settings(self, tmp_path):
        sf = tmp_path / "config.toml"
        sf.write_text(
            '[settings]\nauto_add_clone = true\n\n[projects.p]\npath = "/tmp"\n'
        )
        set_txs_setting("tui_theme", "nord", sf)
        assert get_txs_setting("tui_theme", sf) == "nord"
        assert project_exists("p", sf)

    def test_creates_settings_section_when_missing(self, tmp_path):
        sf = tmp_path / "config.toml"
        sf.write_text('[projects.p]\npath = "/tmp"\n')
        set_txs_setting("fzf_height", "70%", sf)
        assert get_txs_setting("fzf_height", sf) == "70%"
        assert project_exists("p", sf)

    def test_bool_and_int_written_typed(self, tmp_path):
        sf = tmp_path / "config.toml"
        set_txs_setting("auto_add_clone", "false", sf)
        set_txs_setting("worktree_session_max_len", "12", sf)
        text = sf.read_text()
        assert "auto_add_clone = false" in text
        assert "worktree_session_max_len = 12" in text

    def test_preserves_comments(self, tmp_path):
        sf = tmp_path / "config.toml"
        sf.write_text(
            '# my comment\n[settings]\n# keep me\ntui_theme = "textual-dark"\n'
        )
        set_txs_setting("tui_theme", "nord", sf)
        text = sf.read_text()
        assert "# my comment" in text
        assert "# keep me" in text


class TestSettingIsTrue:
    def test_true_when_explicit(self, tmp_path):
        sf = tmp_path / "config.toml"
        sf.write_text("[settings]\nauto_add_clone = true\n")
        assert setting_is_true("auto_add_clone", sf)

    def test_false_when_not_true(self, tmp_path):
        sf = tmp_path / "config.toml"
        sf.write_text("[settings]\nauto_add_clone = false\n")
        assert not setting_is_true("auto_add_clone", sf)


class TestSettingBool:
    def test_default_when_missing(self, tmp_path):
        sf = tmp_path / "config.toml"
        assert setting_bool("tui_trees_expanded", default=True, settings_file=sf)
        assert not setting_bool("tui_trees_expanded", default=False, settings_file=sf)

    def test_explicit_false(self, tmp_path):
        sf = tmp_path / "config.toml"
        sf.write_text("[settings]\ntui_trees_expanded = false\n")
        assert not setting_bool("tui_trees_expanded", default=True, settings_file=sf)


# ---------------------------------------------------------------------------
# Project writers
# ---------------------------------------------------------------------------


class TestProjectWriters:
    def test_add_project_round_trip(self, tmp_path):
        cf = tmp_path / "config.toml"
        add_project("repo", "/tmp/repo", cf)
        assert project_exists("repo", cf)
        assert get_project_prop(parse_config(cf), "repo", "path") == "/tmp/repo"

    def test_add_dotted_name_is_quoted(self, tmp_path):
        cf = tmp_path / "config.toml"
        add_project("a.b", "/tmp/ab", cf)
        assert '[projects."a.b"]' in cf.read_text()
        assert project_exists("a.b", cf)

    def test_remove_project_keeps_others_and_settings(self, tmp_path):
        cf = tmp_path / "config.toml"
        cf.write_text(
            '[settings]\nfzf_height = "60%"\n\n'
            '[projects.one]\npath = "/tmp/1"\n\n'
            '[projects.two]\npath = "/tmp/2"\n'
        )
        remove_project("one", cf)
        assert not project_exists("one", cf)
        assert project_exists("two", cf)
        assert get_txs_setting("fzf_height", cf) == "60%"

    def test_remove_last_project_leaves_no_trailing_blanks(self, tmp_path):
        cf = tmp_path / "config.toml"
        cf.write_text('[projects.only]\npath = "/tmp/o"\n')
        remove_project("only", cf)
        assert cf.read_text() == ""


# ---------------------------------------------------------------------------
# Legacy migration (projects.conf + config  →  config.toml)
# ---------------------------------------------------------------------------


class TestLegacyMigration:
    LEGACY_PROJECTS = """[DEFAULT]
on_create = echo default

[myproject]
path = ~/projects/test
session_name = test-session
on_create = tmux split-window -v
    nvim .

[depthy]
path = /tmp/depthy
max_depth = 2

[plain]
path = /tmp/plain
"""

    LEGACY_SETTINGS = (
        "# old settings\nauto_add_clone = false\nfzf_height = 80%  # custom\n"
    )

    def _write_legacy(self, tmp_path):
        (tmp_path / "projects.conf").write_text(self.LEGACY_PROJECTS)
        (tmp_path / "config").write_text(self.LEGACY_SETTINGS)
        return tmp_path / "config.toml"

    def test_converts_projects_and_settings(self, tmp_path):
        cf = self._write_legacy(tmp_path)
        c = parse_config(cf)

        assert [p.name for p in c.projects] == ["myproject", "depthy", "plain"]
        assert get_project_prop(c, "myproject", "session_name") == "test-session"
        assert "nvim ." in get_project_prop(c, "myproject", "on_create")
        assert get_project_prop(c, "depthy", "max_depth") == "2"
        assert c.default_on_create == "echo default"
        assert get_txs_setting("auto_add_clone", cf) == "false"
        assert get_txs_setting("fzf_height", cf) == "80%"

    def test_keeps_legacy_files_as_bak(self, tmp_path):
        cf = self._write_legacy(tmp_path)
        parse_config(cf)
        assert not (tmp_path / "projects.conf").exists()
        assert (tmp_path / "projects.conf.bak").exists()
        assert not (tmp_path / "config").exists()
        assert (tmp_path / "config.bak").exists()

    def test_does_not_overwrite_existing_config_toml(self, tmp_path):
        cf = tmp_path / "config.toml"
        cf.write_text('[projects.new]\npath = "/tmp/new"\n')
        (tmp_path / "projects.conf").write_text("[old]\npath = /tmp/old\n")
        c = parse_config(cf)
        assert [p.name for p in c.projects] == ["new"]
        assert (tmp_path / "projects.conf").exists()

    def test_migration_runs_once(self, tmp_path):
        cf = self._write_legacy(tmp_path)
        parse_config(cf)
        first = cf.read_text()
        invalidate_config_cache()
        parse_config(cf)
        assert cf.read_text() == first


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class TestReloadConfigIfChanged:
    def test_skips_reparse_when_mtime_unchanged(self, tmp_path, monkeypatch):
        from txs import config as config_mod

        conf = tmp_path / "config.toml"
        conf.write_text('[projects.p]\npath = "/tmp"\n')
        monkeypatch.setattr(config_mod, "CONFIG_FILE", conf)
        invalidate_config_cache()
        first = parse_config()
        first_mtime = conf.stat().st_mtime
        reload_config_if_changed()
        second = parse_config()
        assert first is second
        assert config_mod._config_mtime == first_mtime

    def test_invalidates_when_file_touched(self, tmp_path, monkeypatch):
        from txs import config as config_mod

        conf = tmp_path / "config.toml"
        conf.write_text('[projects.p]\npath = "/tmp"\n')
        monkeypatch.setattr(config_mod, "CONFIG_FILE", conf)
        invalidate_config_cache()
        parse_config()
        conf.write_text('[projects.p]\npath = "/tmp/other"\n')
        reload_config_if_changed()
        assert parse_config()._by_name("p").path == "/tmp/other"


# ---------------------------------------------------------------------------
# Missing config file raises SystemExit
# ---------------------------------------------------------------------------


def test_missing_config_raises(tmp_path):
    with pytest.raises(SystemExit):
        parse_config(tmp_path / "no_such_file.toml")


def test_default_config_path_is_config_toml():
    assert CONFIG_FILE.name == "config.toml"
