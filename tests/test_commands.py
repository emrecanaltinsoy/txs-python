"""
Tests for commands.py — mirrors the bash test suite's command tests.
Uses typer's CliRunner for CLI-level tests.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from txs.__main__ import app
from txs.config import (
    invalidate_config_cache,
    parse_config,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def invoke(*args: str, env: dict | None = None):
    return runner.invoke(app, list(args), env=env or {})


def git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)


def git_commit(path: Path) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        check=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """Redirect CONFIG_FILE and SETTINGS_FILE to tmp_path for every test."""
    import txs.commands as cmd_mod
    import txs.config as cfg_mod

    conf = tmp_path / "projects.conf"
    sett = tmp_path / "config"

    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", conf)
    monkeypatch.setattr(cfg_mod, "SETTINGS_FILE", sett)
    monkeypatch.setattr(cmd_mod, "CONFIG_FILE", conf)
    monkeypatch.setattr(cmd_mod, "SETTINGS_FILE", sett)

    invalidate_config_cache()
    yield
    invalidate_config_cache()


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


class TestVersion:
    def test_version_subcommand(self):
        from txs import TXS_VERSION

        r = invoke("version")
        assert TXS_VERSION in r.output

    def test_version_flag(self):
        from txs import TXS_VERSION

        r = invoke("--version")
        assert TXS_VERSION in r.output

    def test_version_short_flag(self):
        from txs import TXS_VERSION

        r = invoke("-v")
        assert TXS_VERSION in r.output


# ---------------------------------------------------------------------------
# help
# ---------------------------------------------------------------------------


class TestHelp:
    def test_help_flag(self):
        r = invoke("--help")
        assert r.exit_code == 0
        assert "attach" in r.output

    def test_help_mentions_commands(self):
        r = invoke("--help")
        for cmd in ("attach", "ls", "kill", "clone-bare", "wt", "add", "remove"):
            assert cmd in r.output


# ---------------------------------------------------------------------------
# unknown command
# ---------------------------------------------------------------------------


def test_unknown_command_exits_nonzero():
    r = invoke("nonexistent")
    assert r.exit_code != 0


# ---------------------------------------------------------------------------
# ls invalid filter
# ---------------------------------------------------------------------------


def test_ls_invalid_filter(tmp_path, monkeypatch):
    import txs.config as cfg_mod

    conf = tmp_path / "projects.conf"
    conf.touch()
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", conf)

    r = invoke("ls", "invalid")
    assert r.exit_code != 0
    assert "Unknown filter" in r.output or "Unknown filter" in r.stderr


# ---------------------------------------------------------------------------
# config invalid target
# ---------------------------------------------------------------------------


def test_config_invalid_target():
    r = invoke("config", "invalid")
    assert r.exit_code != 0
    assert "Unknown config target" in r.output or "Unknown config target" in r.stderr


# ---------------------------------------------------------------------------
# wt subcommands (outside git repo)
# ---------------------------------------------------------------------------


class TestWtOutsideGitRepo:
    def _run_outside_repo(self, *args):
        """Run wt subcommand with CWD = /tmp (no git repo)."""
        orig = os.getcwd()
        try:
            os.chdir("/tmp")
            return invoke(*args)
        finally:
            os.chdir(orig)

    def test_wt_add_outside_repo(self):
        r = self._run_outside_repo("wt", "add", "somebranch")
        assert r.exit_code != 0

    def test_wt_list_outside_repo(self):
        r = self._run_outside_repo("wt", "list")
        assert r.exit_code != 0


# ---------------------------------------------------------------------------
# wt add/remove — missing branch (non-interactive)
# ---------------------------------------------------------------------------


def test_wt_add_missing_branch_noninteractive(tmp_path):
    git_init(tmp_path)
    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        r = runner.invoke(app, ["wt", "add"], input="")
        assert r.exit_code != 0
    finally:
        os.chdir(orig)


def test_wt_remove_missing_branch_noninteractive(tmp_path):
    git_init(tmp_path)
    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        r = runner.invoke(app, ["wt", "remove"], input="")
        assert r.exit_code != 0
    finally:
        os.chdir(orig)


# ---------------------------------------------------------------------------
# aliases
# ---------------------------------------------------------------------------


def test_list_alias_same_as_ls(tmp_path, monkeypatch):
    import txs.config as cfg_mod

    conf = tmp_path / "projects.conf"
    conf.touch()
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", conf)

    r_ls = invoke("ls")
    r_list = invoke("list")
    # Both should succeed (or fail for the same reason — no tmux)
    assert r_ls.exit_code == r_list.exit_code


# ---------------------------------------------------------------------------
# remove missing arg
# ---------------------------------------------------------------------------


def test_remove_missing_arg():
    r = invoke("remove")
    assert r.exit_code != 0


# ---------------------------------------------------------------------------
# clone-bare missing arg
# ---------------------------------------------------------------------------


def test_clone_bare_missing_arg():
    r = invoke("clone-bare")
    assert r.exit_code != 0


# ---------------------------------------------------------------------------
# cmd_add
# ---------------------------------------------------------------------------


class TestCmdAdd:
    def test_add_reports_success(self, tmp_path, monkeypatch):
        import txs.commands as cmd_mod
        import txs.config as cfg_mod

        conf = tmp_path / "projects.conf"
        monkeypatch.setattr(cfg_mod, "CONFIG_FILE", conf)
        monkeypatch.setattr(cmd_mod, "CONFIG_FILE", conf)
        invalidate_config_cache()

        proj_dir = tmp_path / "my-project"
        proj_dir.mkdir()

        r = invoke("add", str(proj_dir))
        assert r.exit_code == 0
        assert "Added project" in r.output

    def test_config_file_created(self, tmp_path, monkeypatch):
        import txs.commands as cmd_mod
        import txs.config as cfg_mod

        conf = tmp_path / "projects.conf"
        monkeypatch.setattr(cfg_mod, "CONFIG_FILE", conf)
        monkeypatch.setattr(cmd_mod, "CONFIG_FILE", conf)
        invalidate_config_cache()

        (tmp_path / "p").mkdir()
        invoke("add", str(tmp_path / "p"))
        assert conf.exists()

    def test_project_appears_in_config(self, tmp_path, monkeypatch):
        import txs.commands as cmd_mod
        import txs.config as cfg_mod

        conf = tmp_path / "projects.conf"
        monkeypatch.setattr(cfg_mod, "CONFIG_FILE", conf)
        monkeypatch.setattr(cmd_mod, "CONFIG_FILE", conf)
        invalidate_config_cache()

        proj_dir = tmp_path / "my-project"
        proj_dir.mkdir()
        invoke("add", str(proj_dir))

        invalidate_config_cache()
        cfg = parse_config(conf)
        assert len(cfg.projects) == 1
        assert cfg.projects[0].name == "my-project"

    def test_path_stored_correctly(self, tmp_path, monkeypatch):
        import txs.commands as cmd_mod
        import txs.config as cfg_mod

        conf = tmp_path / "projects.conf"
        monkeypatch.setattr(cfg_mod, "CONFIG_FILE", conf)
        monkeypatch.setattr(cmd_mod, "CONFIG_FILE", conf)
        invalidate_config_cache()

        proj_dir = tmp_path / "my-project"
        proj_dir.mkdir()
        invoke("add", str(proj_dir))

        invalidate_config_cache()
        cfg = parse_config(conf)
        from txs.config import get_project_prop

        assert get_project_prop(cfg, "my-project", "path") == str(proj_dir)

    def test_duplicate_add_fails(self, tmp_path, monkeypatch):
        import txs.commands as cmd_mod
        import txs.config as cfg_mod

        conf = tmp_path / "projects.conf"
        monkeypatch.setattr(cfg_mod, "CONFIG_FILE", conf)
        monkeypatch.setattr(cmd_mod, "CONFIG_FILE", conf)
        invalidate_config_cache()

        proj_dir = tmp_path / "my-project"
        proj_dir.mkdir()
        invoke("add", str(proj_dir))
        invalidate_config_cache()

        r = invoke("add", str(proj_dir))
        assert r.exit_code != 0
        assert "already exists" in r.output or "already exists" in r.stderr

    def test_nonexistent_path_fails(self, tmp_path, monkeypatch):
        import txs.commands as cmd_mod
        import txs.config as cfg_mod

        conf = tmp_path / "projects.conf"
        monkeypatch.setattr(cfg_mod, "CONFIG_FILE", conf)
        monkeypatch.setattr(cmd_mod, "CONFIG_FILE", conf)

        r = invoke("add", str(tmp_path / "no-such-dir"))
        assert r.exit_code != 0
        assert "does not exist" in r.output or "does not exist" in r.stderr

    def test_spaces_in_name_sanitized(self, tmp_path, monkeypatch):
        import txs.commands as cmd_mod
        import txs.config as cfg_mod

        conf = tmp_path / "projects2.conf"
        monkeypatch.setattr(cfg_mod, "CONFIG_FILE", conf)
        monkeypatch.setattr(cmd_mod, "CONFIG_FILE", conf)
        invalidate_config_cache()

        proj_dir = tmp_path / "cool project"
        proj_dir.mkdir()
        r = invoke("add", str(proj_dir))
        assert r.exit_code == 0

        invalidate_config_cache()
        cfg = parse_config(conf)
        assert cfg.projects[0].name == "cool-project"

    def test_spaces_in_path_preserved(self, tmp_path, monkeypatch):
        import txs.commands as cmd_mod
        import txs.config as cfg_mod

        conf = tmp_path / "projects2.conf"
        monkeypatch.setattr(cfg_mod, "CONFIG_FILE", conf)
        monkeypatch.setattr(cmd_mod, "CONFIG_FILE", conf)
        invalidate_config_cache()

        proj_dir = tmp_path / "cool project"
        proj_dir.mkdir()
        invoke("add", str(proj_dir))

        invalidate_config_cache()
        cfg = parse_config(conf)
        from txs.config import get_project_prop

        assert get_project_prop(cfg, "cool-project", "path") == str(proj_dir)


# ---------------------------------------------------------------------------
# cmd_remove
# ---------------------------------------------------------------------------


class TestCmdRemove:
    @pytest.fixture()
    def conf_with_project(self, tmp_path, monkeypatch):
        import txs.commands as cmd_mod
        import txs.config as cfg_mod

        conf = tmp_path / "projects.conf"
        monkeypatch.setattr(cfg_mod, "CONFIG_FILE", conf)
        monkeypatch.setattr(cmd_mod, "CONFIG_FILE", conf)
        invalidate_config_cache()

        proj_dir = tmp_path / "my-project"
        proj_dir.mkdir()
        invoke("add", str(proj_dir))
        invalidate_config_cache()
        return conf

    def test_remove_reports_success(self, conf_with_project):
        r = invoke("remove", "my-project")
        assert r.exit_code == 0
        assert "Removed project" in r.output

    def test_project_gone_from_config(self, conf_with_project):
        invoke("remove", "my-project")
        invalidate_config_cache()
        cfg = parse_config(conf_with_project)
        assert len(cfg.projects) == 0

    def test_remove_nonexistent_fails(self, conf_with_project):
        r = invoke("remove", "nonexistent")
        assert r.exit_code != 0
        assert "not found" in r.output or "not found" in r.stderr


# ---------------------------------------------------------------------------
# cmd_clone_bare  (integration test with a local bare repo)
# ---------------------------------------------------------------------------


class TestCloneBare:
    @pytest.fixture()
    def origin_repo(self, tmp_path):
        origin = tmp_path / "origin-repo"
        origin.mkdir()
        subprocess.run(
            ["git", "init", "--bare", str(origin)], check=True, capture_output=True
        )
        work = tmp_path / "work"
        subprocess.run(
            ["git", "clone", str(origin), str(work)], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(work), "config", "user.email", "t@t"], check=True
        )
        subprocess.run(["git", "-C", str(work), "config", "user.name", "T"], check=True)
        subprocess.run(
            ["git", "-C", str(work), "commit", "--allow-empty", "-m", "init"],
            check=True,
            capture_output=True,
        )
        # push to main or master
        for branch in ("main", "master"):
            r = subprocess.run(
                ["git", "-C", str(work), "push", "origin", branch],
                capture_output=True,
            )
            if r.returncode == 0:
                break
        return origin, tmp_path

    def test_clone_bare_creates_bare_dir(self, origin_repo, tmp_path, monkeypatch):
        import txs.commands as cmd_mod
        import txs.config as cfg_mod

        conf = tmp_path / "clone-projects.conf"
        monkeypatch.setattr(cfg_mod, "CONFIG_FILE", conf)
        monkeypatch.setattr(cmd_mod, "CONFIG_FILE", conf)
        monkeypatch.setattr(cmd_mod, "SETTINGS_FILE", tmp_path / "clone-settings")
        invalidate_config_cache()

        origin, _base = origin_repo
        clone_dir = tmp_path / "clone-test"
        clone_dir.mkdir()

        orig_cwd = os.getcwd()
        try:
            os.chdir(clone_dir)
            r = invoke("clone-bare", str(origin), "myrepo")
        finally:
            os.chdir(orig_cwd)

        assert r.exit_code == 0
        assert "Success!" in r.output
        assert (clone_dir / "myrepo" / ".bare").is_dir()
        assert (clone_dir / "myrepo" / ".git").is_file()

    def test_clone_bare_creates_worktree(self, origin_repo, tmp_path, monkeypatch):
        import txs.commands as cmd_mod
        import txs.config as cfg_mod

        conf = tmp_path / "clone-projects.conf"
        monkeypatch.setattr(cfg_mod, "CONFIG_FILE", conf)
        monkeypatch.setattr(cmd_mod, "CONFIG_FILE", conf)
        monkeypatch.setattr(cmd_mod, "SETTINGS_FILE", tmp_path / "clone-settings")
        invalidate_config_cache()

        origin, _ = origin_repo
        clone_dir = tmp_path / "clone-test2"
        clone_dir.mkdir()

        orig_cwd = os.getcwd()
        try:
            os.chdir(clone_dir)
            invoke("clone-bare", str(origin), "myrepo")
        finally:
            os.chdir(orig_cwd)

        # One of main.branch or master.branch should exist
        wt_main = clone_dir / "myrepo" / "myrepo.main"
        wt_master = clone_dir / "myrepo" / "myrepo.master"
        assert wt_main.is_dir() or wt_master.is_dir()

    def test_clone_bare_auto_add(self, origin_repo, tmp_path, monkeypatch):
        import txs.commands as cmd_mod
        import txs.config as cfg_mod

        conf = tmp_path / "clone-projects.conf"
        sett = tmp_path / "clone-settings"
        sett.write_text("auto_add_clone = true\n")
        monkeypatch.setattr(cfg_mod, "CONFIG_FILE", conf)
        monkeypatch.setattr(cfg_mod, "SETTINGS_FILE", sett)
        monkeypatch.setattr(cmd_mod, "CONFIG_FILE", conf)
        monkeypatch.setattr(cmd_mod, "SETTINGS_FILE", sett)
        invalidate_config_cache()

        origin, _ = origin_repo
        clone_dir = tmp_path / "clone-test3"
        clone_dir.mkdir()

        orig_cwd = os.getcwd()
        try:
            os.chdir(clone_dir)
            invoke("clone-bare", str(origin), "myrepo")
        finally:
            os.chdir(orig_cwd)

        assert conf.exists()
