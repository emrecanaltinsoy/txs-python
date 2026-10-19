"""
git / worktree helpers — mirrors git.sh.

Depth scanning uses pure file tests (no git fork per directory), matching the
performance optimisation in the bash version.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Bare-repo detection
# ---------------------------------------------------------------------------


def is_bare_repo(path: str) -> bool:
    """True if path is a bare-repo in our clone-bare layout, or a standard bare repo."""
    p = Path(path)
    # Our layout: .bare/ sub-directory
    if (p / ".bare").is_dir():
        return True
    # Standard bare repo check
    result = subprocess.run(
        ["git", "-C", path, "rev-parse", "--is-bare-repository"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "true"


# ---------------------------------------------------------------------------
# Worktree listing
# ---------------------------------------------------------------------------


def _list_worktree_paths(path: str) -> list[str]:
    """Parse 'git worktree list --porcelain', return non-bare worktree paths."""
    result = subprocess.run(
        ["git", "-C", path, "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
    )
    paths: list[str] = []
    current: str = ""
    is_bare = False
    for line in result.stdout.splitlines():
        if not line:
            if current and not is_bare:
                paths.append(current)
            current = ""
            is_bare = False
            continue
        if line.startswith("worktree "):
            current = line[len("worktree ") :]
        elif line == "bare":
            is_bare = True
    # flush last entry if no trailing blank line
    if current and not is_bare:
        paths.append(current)
    return paths


def get_project_worktrees(path: str) -> list[tuple[str, str]]:
    """Return list of (worktree_path, basename) for a repo."""
    return [(wt, os.path.basename(wt)) for wt in _list_worktree_paths(path)]


# ---------------------------------------------------------------------------
# Repo info from CWD
# ---------------------------------------------------------------------------


def get_repo_info() -> tuple[str, str]:
    """
    Detect repo root and type from the current directory.
    Returns (root, type) where type is 'bare' or 'normal'.
    Raises SystemExit(1) if not inside a git repo.
    """
    from txs.log import error

    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        error("Not inside a git repository.")
        raise SystemExit(1)

    # Check for our bare layout (.bare/ directory)
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
    ).stdout.strip()

    if common:
        if not os.path.isabs(common):
            common = str(Path(common).resolve())
        if os.path.basename(common) == ".bare":
            root = str(Path(common).parent.resolve())
            return root, "bare"

    # Normal repo
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if top.returncode != 0:
        error("Could not determine repository root.")
        raise SystemExit(1)
    root = str(Path(top.stdout.strip()).resolve())
    return root, "normal"


# ---------------------------------------------------------------------------
# Worktree path computation
# ---------------------------------------------------------------------------


def wt_path(root: str, repo_type: str, branch: str) -> str:
    """
    Compute the worktree directory path for a branch.
    Bare:   <root>/<reponame>.<branch>
    Normal: <parent of root>/<reponame>.<branch>
    """
    dir_name = f"{os.path.basename(root)}.{branch}"
    if repo_type == "bare":
        return os.path.join(root, dir_name)
    return os.path.join(os.path.dirname(root), dir_name)


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def repo_name_from_url(url: str) -> str:
    name = os.path.basename(url.rstrip("/"))
    name = name.removesuffix(".git")
    return name


def depth_session_name(wt_path_str: str) -> str:
    """
    Session name for a depth-discovered worktree:
    bare-repo layout  → repo root basename
    normal            → worktree basename
    """
    parent = os.path.dirname(wt_path_str)
    if is_bare_repo(parent):
        return os.path.basename(parent)
    return os.path.basename(wt_path_str)


# ---------------------------------------------------------------------------
# Active worktrees (from open tmux panes)
# ---------------------------------------------------------------------------


def get_active_worktrees() -> list[tuple[str, str, str]]:
    """
    Returns list of (session, worktree_path, label).
    label = '<repo_name> - <worktree_basename>'
    """
    result = subprocess.run(
        ["tmux", "list-panes", "-a", "-F", "#{session_name}|#{pane_current_path}"],
        capture_output=True,
        text=True,
    )
    seen: set[str] = set()
    entries: list[tuple[str, str, str]] = []

    for line in result.stdout.splitlines():
        if not line:
            continue
        session, _, pane_path = line.partition("|")
        if not session or not pane_path:
            continue

        git_check = subprocess.run(
            ["git", "-C", pane_path, "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
        )
        if git_check.returncode != 0:
            continue

        git_dir = git_check.stdout.strip()
        if not os.path.isabs(git_dir):
            git_dir = str(Path(pane_path) / git_dir)

        # Derive repo name
        origin = subprocess.run(
            ["git", "-C", pane_path, "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
        ).stdout.strip()

        if origin:
            repo_name = repo_name_from_url(origin)
        else:
            base = os.path.basename(git_dir)
            if base in (".bare", ".git"):
                repo_name = os.path.basename(os.path.dirname(git_dir))
            else:
                repo_name = base

        for wt in _list_worktree_paths(pane_path):
            if wt in seen:
                continue
            seen.add(wt)
            label = f"{repo_name} - {os.path.basename(wt)}"
            entries.append((session, wt, label))

    return entries


# ---------------------------------------------------------------------------
# Depth scanning  (mirrors get_depth_projects / _scan_depth_dir in git.sh)
# ---------------------------------------------------------------------------


def get_depth_projects(root: str, max_depth: int) -> list[tuple[str, str]]:
    """
    Scan subdirectories up to max_depth for git repos.
    Stops descending into a directory once it is identified as a git repo.
    Returns list of (abs_path, basename).
    """
    if not os.path.isdir(root) or max_depth <= 0:
        return []
    try:
        phys_root = str(Path(root).resolve())
    except OSError:
        return []
    results: list[tuple[str, str]] = []
    _scan_depth_dir(phys_root, max_depth, 0, results)
    return results


def _dir_owns_repo(path: str) -> bool:
    """
    Return True if `path` owns a git repo (pure file tests, no git fork).
    Mirrors _dir_owns_repo in git.sh.
    """
    git_dir = os.path.join(path, ".git")

    if os.path.isdir(git_dir):
        return os.path.isfile(os.path.join(git_dir, "HEAD"))

    if os.path.isfile(git_dir):
        try:
            with open(git_dir) as f:
                line = f.readline().strip()
        except OSError:
            return False
        if not line.startswith("gitdir: "):
            return False
        gd = line[len("gitdir: ") :]
        if not os.path.isabs(gd):
            gd = os.path.join(path, gd)
        gd = _normalize_abs_path(gd)
        if not os.path.isdir(gd):
            return False
        # Only count it if the gitdir is *inside* this directory
        return gd.startswith(path + os.sep)

    # Standard bare repo: HEAD + objects/ + refs/
    return (
        os.path.isfile(os.path.join(path, "HEAD"))
        and os.path.isdir(os.path.join(path, "objects"))
        and os.path.isdir(os.path.join(path, "refs"))
    )


def _normalize_abs_path(path: str) -> str:
    """Lexically normalize an absolute path (resolve . and ..), no forks."""
    parts: list[str] = []
    for part in path.split(os.sep):
        if part in ("", "."):
            continue
        elif part == "..":
            if parts:
                parts.pop()
        else:
            parts.append(part)
    return os.sep + os.sep.join(parts)


def _scan_depth_dir(
    directory: str,
    max_depth: int,
    current_depth: int,
    results: list[tuple[str, str]],
) -> None:
    next_depth = current_depth + 1
    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        return

    for name in entries:
        if name.startswith("."):
            continue  # skip hidden dirs

        abs_sub = os.path.join(directory, name)

        if os.path.islink(abs_sub):
            try:
                abs_sub = str(Path(abs_sub).resolve())
            except OSError:
                continue

        if not os.path.isdir(abs_sub):
            continue

        if _dir_owns_repo(abs_sub):
            results.append((abs_sub, name))
        elif next_depth < max_depth:
            _scan_depth_dir(abs_sub, max_depth, next_depth, results)
