"""Tests for git.py — mirrors the bash depth-scan and repo-detection tests."""

import subprocess
from pathlib import Path

import pytest

from txs.config import (
    build_depth_index,
    find_depth_owner,
    parse_config,
)
from txs.git import (
    _dir_owns_repo,
    _normalize_abs_path,
    depth_session_name,
    get_depth_projects,
    wt_path,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def git_init(path: Path, bare: bool = False) -> None:
    args = ["git", "init", "-q"]
    if bare:
        args.append("--bare")
    args.append(str(path))
    subprocess.run(args, check=True)


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


def git_worktree_add(repo: Path, dest: Path, branch: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", str(dest), "-b", branch],
        check=True,
    )


# ---------------------------------------------------------------------------
# _normalize_abs_path
# ---------------------------------------------------------------------------


def test_normalize_abs_path():
    assert _normalize_abs_path("/a/b/../c/./d") == "/a/c/d"


def test_normalize_abs_path_trailing():
    assert _normalize_abs_path("/a/b/c/") == "/a/b/c"


# ---------------------------------------------------------------------------
# _dir_owns_repo
# ---------------------------------------------------------------------------


class TestDirOwnsRepo:
    def test_normal_repo(self, tmp_path):
        git_init(tmp_path / "repo")
        assert _dir_owns_repo(str(tmp_path / "repo"))

    def test_bare_repo(self, tmp_path):
        git_init(tmp_path / "bare.git", bare=True)
        assert _dir_owns_repo(str(tmp_path / "bare.git"))

    def test_our_bare_layout(self, tmp_path):
        # .bare/ sub-directory + .git file pointing inside
        bare_root = tmp_path / "myrepo"
        bare_root.mkdir()
        src = tmp_path / "src"
        git_init(src)
        git_commit(src)
        subprocess.run(
            ["git", "clone", "-q", "--bare", str(src), str(bare_root / ".bare")],
            check=True,
        )
        (bare_root / ".git").write_text("gitdir: ./.bare\n")
        assert _dir_owns_repo(str(bare_root))

    def test_worktree_sibling_not_owned(self, tmp_path):
        # A worktree sibling has a .git file pointing *outside* the dir
        repo = tmp_path / "repo"
        git_init(repo)
        git_commit(repo)
        sibling = tmp_path / "repo.feat"
        git_worktree_add(repo, sibling, "feat")
        # sibling/.git points to ../repo/.git/worktrees/feat — outside sibling
        assert not _dir_owns_repo(str(sibling))

    def test_plain_dir(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert not _dir_owns_repo(str(plain))


# ---------------------------------------------------------------------------
# get_depth_projects
# ---------------------------------------------------------------------------


class TestGetDepthProjects:
    """Mirrors the 'depth scan detects repos only' bash test."""

    @pytest.fixture()
    def scan_root(self, tmp_path):
        sr = tmp_path / "root"
        sr.mkdir()

        # plain repo
        git_init(sr / "plain")

        # repo with a worktree sibling (sibling should NOT appear)
        git_init(sr / "sib")
        git_commit(sr / "sib")
        git_worktree_add(sr / "sib", tmp_path / "sib.feat", "feat")

        # our bare-layout repo
        src = tmp_path / "src"
        git_init(src)
        git_commit(src)
        subprocess.run(
            ["git", "clone", "-q", "--bare", str(src), str(sr / "bareroot" / ".bare")],
            check=True,
        )
        (sr / "bareroot" / ".git").write_text("gitdir: ./.bare\n")

        # standard bare repo
        git_init(sr / "bare.git", bare=True)

        # nested repo (requires depth >= 2 to find)
        (sr / "notrepo" / "deep").mkdir(parents=True)
        git_init(sr / "notrepo" / "deep")

        # hidden directory — must be skipped
        (sr / ".hidden" / "x").mkdir(parents=True)
        git_init(sr / ".hidden" / "x")

        # worktree sibling pointing outside — not an owned repo
        (sr / "outside-ref").mkdir()
        (sr / "outside-ref" / ".git").write_text("gitdir: ../plain/.git\n")

        return sr

    def test_finds_expected_names_depth2(self, scan_root):
        results = get_depth_projects(str(scan_root), 2)
        names = sorted(n for _, n in results)
        assert names == ["bare.git", "bareroot", "deep", "plain", "sib"]

    def test_depth1_misses_nested(self, scan_root):
        results = get_depth_projects(str(scan_root), 1)
        names = sorted(n for _, n in results)
        assert "deep" not in names

    def test_hidden_excluded(self, scan_root):
        results = get_depth_projects(str(scan_root), 2)
        names = [n for _, n in results]
        assert "x" not in names

    def test_worktree_sibling_excluded(self, scan_root, tmp_path):
        results = get_depth_projects(str(scan_root), 2)
        names = [n for _, n in results]
        assert "feat" not in names

    def test_empty_dir(self, tmp_path):
        assert get_depth_projects(str(tmp_path / "nonexistent"), 2) == []

    def test_max_depth_zero(self, scan_root):
        assert get_depth_projects(str(scan_root), 0) == []


# ---------------------------------------------------------------------------
# wt_path
# ---------------------------------------------------------------------------


class TestWtPath:
    def test_bare(self):
        result = wt_path("/home/user/myrepo", "bare", "main")
        assert result == "/home/user/myrepo/myrepo.main"

    def test_normal(self):
        result = wt_path("/home/user/myrepo", "normal", "feat")
        assert result == "/home/user/myrepo.feat"


# ---------------------------------------------------------------------------
# depth_session_name
# ---------------------------------------------------------------------------


class TestDepthSessionName:
    def test_bare_worktree_uses_root_name(self, tmp_path):
        src = tmp_path / "src"
        git_init(src)
        git_commit(src)
        bare_root = tmp_path / "bareroot"
        bare_root.mkdir()
        subprocess.run(
            ["git", "clone", "-q", "--bare", str(src), str(bare_root / ".bare")],
            check=True,
        )
        (bare_root / ".git").write_text("gitdir: ./.bare\n")
        git_commit_path = str(bare_root)
        wt = bare_root / "main"
        subprocess.run(
            [
                "git",
                "-C",
                git_commit_path,
                "worktree",
                "add",
                "-q",
                "-b",
                "wt-main",
                str(wt),
            ],
            check=True,
        )
        assert depth_session_name(str(wt)) == "bareroot"

    def test_normal_repo_uses_own_name(self, tmp_path):
        git_init(tmp_path / "plain")
        assert depth_session_name(str(tmp_path / "plain")) == "plain"


# ---------------------------------------------------------------------------
# Depth owner index  (build_depth_index / find_depth_owner)
# ---------------------------------------------------------------------------


class TestDepthOwnerIndex:
    @pytest.fixture()
    def owner_env(self, tmp_path):
        """
        Two depth projects (pa, pb) each with a repo named 'dup'.
        Also an explicit (non-depth) project at a/x/only-a.
        """
        for path in ["a/x/dup", "a/x/only-a", "b/y/dup", "b/y/only-b"]:
            git_init(tmp_path / path)

        conf = tmp_path / "projects.conf"
        conf.write_text(
            f"[pa]\npath = {tmp_path / 'a'}\nmax_depth = 2\n\n"
            f"[pb]\npath = {tmp_path / 'b'}\nmax_depth = 2\n\n"
            f"[explicit-a]\npath = {tmp_path / 'a' / 'x' / 'only-a'}\n"
        )
        cfg = parse_config(conf)
        build_depth_index(cfg)
        return cfg, tmp_path

    def test_dup_owned_by_last_project(self, owner_env):
        cfg, _tmp_path = owner_env
        result = find_depth_owner(cfg, "dup")
        assert result is not None
        proj, _ = result
        assert proj == "pb"

    def test_unique_basename_found(self, owner_env):
        cfg, _tmp_path = owner_env
        result = find_depth_owner(cfg, "only-b")
        assert result is not None
        proj, path = result
        assert proj == "pb"
        assert "only-b" in path

    def test_explicit_project_excluded_from_depth_owners(self, owner_env):
        cfg, _ = owner_env
        # only-a is an explicit project, so find_depth_owner should not find it
        result = find_depth_owner(cfg, "only-a")
        assert result is None

    def test_missing_basename_returns_none(self, owner_env):
        cfg, _ = owner_env
        assert find_depth_owner(cfg, "missing") is None

    def test_index_built_once(self, owner_env):
        cfg, tmp_path = owner_env
        # Adding a new repo after index is built should NOT be visible
        git_init(tmp_path / "b" / "y" / "late")
        result = find_depth_owner(cfg, "late")
        assert result is None
