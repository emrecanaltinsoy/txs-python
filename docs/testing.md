# Testing Guide for txs-python

This guide covers testing practices, patterns, and guidelines for contributing to txs-python.

## Test Organization

Tests are organized by module in the `tests/` directory:

| File | Tests |
|------|-------|
| `tests/test_config.py` | 47 tests: config parsing, settings, DEFAULT sections, INI parsing |
| `tests/test_git.py` | 21 tests: git detection, worktrees, depth scanning, bare repos |
| `tests/test_commands.py` | 21 tests: CLI commands (add, remove, attach, kill, clone-bare, wt, etc.) |
| `tests/test_tmux.py` | 3 tests: Tmux session operations, window management |

**Total:** 92 tests

## Running Tests

```bash
# Run all tests
pytest

# Verbose output
pytest -v

# Specific test file
pytest tests/test_git.py

# Specific test class
pytest tests/test_git.py::TestDepthSessionName

# Specific test function
pytest tests/test_git.py::TestDepthSessionName::test_bare_worktree_uses_root_name

# With coverage report (terminal)
pytest --cov=txs --cov-report=term-missing

# With coverage report (HTML)
pytest --cov=txs --cov-report=html
```

## Test Patterns

### 1. Using Fixtures

The `conftest.py` provides `tmp_path` for isolated test environments:

```python
def test_parsing(tmp_path):
    """Test config parsing with temporary directory."""
    from txs.config import parse_config

    config_content = """
    [myproject]
    path = {tmp_path}/project
    """

    config = parse_config(tmp_path / "projects.conf")
    assert len(config.projects) == 1
```

### 2. Using Test Helpers

The tests define helper functions for setup:

```python
def git_init(path: Path, bare: bool = False) -> None:
    """Initialize a git repo (or bare repo) at path."""
    args = ["git", "init", "-q"]
    if bare:
        args.append("--bare")
    args.append(str(path))
    subprocess.run(args, check=True)

def git_commit(path: Path) -> None:
    """Create an empty commit at path."""
    subprocess.run([
        "git", "-C", str(path),
        "-c", "user.email=t@t",
        "-c", "user.name=t",
        "commit", "-q", "--allow-empty", "-m", "init",
    ], check=True)

# Usage in test:
def test_bare_repo_detection(tmp_path):
    git_init(tmp_path, bare=True)
    assert is_bare_repo(str(tmp_path)) is True
```

### 3. Config Helper Pattern

Tests use a `cfg()` helper to simplify config tests:

```python
def cfg(content: str, tmp_path: Path) -> ProjectConfig:
    """Write content to a temp projects.conf and parse it."""
    p = tmp_path / "projects.conf"
    p.write_text(content)
    return parse_config(p)

# Usage in test:
class TestBasicParsing:
    CONF = """
    [DEFAULT]
    on_create = echo default

    [myproject]
    path = ~/projects/test
    """

    def test_project_count(self, tmp_path):
        c = cfg(self.CONF, tmp_path)
        assert len(c.projects) == 2
```

### 4. Parameterized Tests

Use `pytest.mark.parametrize` for multiple input cases:

```python
import pytest

def test_dot_replaced(session_name, expected):
    """Test that dots are replaced with dashes."""
    from txs.config import get_project_prop
    assert get_project_prop(None, "test.project", "session_name") == "test-project"

@pytest.mark.parametrize(
    "session_name,expected",
    [
        ("my.project", "my-project"),
        ("my:project", "my-project"),
        ("valid_name", "valid_name"),
    ],
)
```

### 5. Error Conditions

Test that invalid inputs raise appropriate errors:

```python
def test_missing_config_raises(tmp_path):
    """Test that missing config raises an error."""
    from txs.config import parse_config

    # This should raise when config file doesn't exist
    with pytest.raises(SystemExit):
        parse_config(tmp_path / "nonexistent.conf")
```

### 6. Multi-line Config Testing

Test multi-line `on_create` commands:

```python
def test_continuation_appended(tmp_path):
    """Test multi-line on_create commands."""
    config = """
    [myproject]
    path = {tmp_path}/project
    on_create = command1
        command2
        command3
    """

    config_obj = cfg(config, tmp_path)
    assert "command1" in config_obj.projects[0].on_create
    assert "command2" in config_obj.projects[0].on_create
```

### 7. Monkeypatch for File System Tests

Use `monkeypatch` for testing config reload behavior:

```python
def test_invalidates_when_file_touched(tmp_path, monkeypatch):
    """Test that config is reloaded when file is modified."""
    from txs.config import parse_config, invalidate_config_cache

    # Write config
    (tmp_path / "projects.conf").write_text("[test]\npath = /tmp/test")
    parse_config(tmp_path / "projects.conf")

    # Monkeypatch mtime to be newer
    monkeypatch.setattr(
        (tmp_path / "projects.conf"),
        "stat",
        lambda: type("obj", (object,), {"st_mtime": float("inf")})(),
    )

    # Config should be reloaded
    # ...
```

## Test Structure

### Test Classes

Related functionality is organized into test classes:

```python
class TestBasicParsing:
    """Tests for basic config parsing."""

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
```

### Helper Functions

The tests define helper functions for repeated setup:

```python
def git_init(path: Path, bare: bool = False) -> None:
    """Initialize a git repo (or bare repo) at path."""
    args = ["git", "init", "-q"]
    if bare:
        args.append("--bare")
    args.append(str(path))
    subprocess.run(args, check=True)

def git_commit(path: Path) -> None:
    """Create an empty commit at path."""
    subprocess.run([
        "git", "-C", str(path),
        "-c", "user.email=t@t",
        "-c", "user.name=t",
        "commit", "-q", "--allow-empty", "-m", "init",
    ], check=True)

def git_worktree_add(repo: Path, dest: Path, branch: str) -> None:
    """Add a worktree to a repo."""
    subprocess.run([
        "git", "-C", str(repo),
        "worktree", "add", "-q", str(dest), "-b", branch,
    ], check=True)
```

## Coverage Guidelines

When adding a new feature:

1. **Happy path** — basic functionality works
2. **Edge cases** — empty inputs, special characters, limits
3. **Error handling** — invalid inputs, missing files, permissions
4. **Config integration** — feature works with config parsing
5. **TUI integration** — if applicable, test panel rendering

### Example: Testing a New Config Option

```python
def test_new_option(tmp_path):
    """Test the new feature with valid input."""
    config = """
    [myproject]
    path = {tmp_path}/project
    new_option = true
    """
    cfg_obj = parse_config(tmp_path / "projects.conf")
    assert cfg_obj.projects[0].new_option == True

def test_new_option_default(tmp_path):
    """Test that new_option has a sensible default."""
    config = """
    [myproject]
    path = {tmp_path}/project
    """
    cfg_obj = parse_config(tmp_path / "projects.conf")
    assert cfg_obj.projects[0].new_option == False

def test_new_option_invalid(tmp_path):
    """Test that invalid option values raise errors."""
    config = """
    [myproject]
    path = {tmp_path}/project
    new_option = invalid_value
    """
    with pytest.raises(ValueError):
        parse_config(tmp_path / "projects.conf")
```

## Performance Testing

When making changes to the TUI:

- Run tests with `pytest -v` to see timing
- Watch for N+1 queries in loops
- Ensure new code doesn't increase refresh time
- Consider using the refresh bundle pattern

## Test File Template

```python
"""Tests for module.py — brief description."""

import subprocess
from pathlib import Path

import pytest

from txs.config import parse_config
from txs.module import function_name

# Helpers
def git_init(path: Path, bare: bool = False) -> None:
    """Initialize a git repo at path."""
    args = ["git", "init", "-q"]
    if bare:
        args.append("--bare")
    args.append(str(path))
    subprocess.run(args, check=True)

def cfg(content: str, tmp_path: Path) -> ProjectConfig:
    """Write content to a temp projects.conf and parse it."""
    p = tmp_path / "projects.conf"
    p.write_text(content)
    return parse_config(p)

class TestFunctionName:
    """Tests for function_name()."""

    CONF = """
    [myproject]
    path = ~/projects/test
    """

    def test_happy_path(self, tmp_path):
        """Test basic functionality."""
        config = cfg(self.CONF, tmp_path)
        assert len(config.projects) == 1

    def test_edge_case(self, tmp_path):
        """Test edge case."""
        git_init(tmp_path)
        assert is_git_repo(str(tmp_path)) is True

    def test_error_handling(self):
        """Test error conditions."""
        with pytest.raises(ValueError):
            function_name(invalid_input)

@pytest.mark.parametrize("input,expected", [
    ("case1", "result1"),
    ("case2", "result2"),
])
def test_parameterized(input, expected):
    """Test with multiple cases."""
    from txs.git import function_name
    assert function_name(input) == expected
```

## Common Pitfalls

### 1. Testing tmux/git subprocesses

Don't run actual subprocesses in tests. Mock them:

```python
# BAD: Runs actual git command
def test_git_detection():
    subprocess.run(["git", "rev-parse", "--is-inside-work-tree"])

# GOOD: Mocks subprocess
def test_git_detection(tmp_path):
    with patch('subprocess.run') as mock:
        mock.return_value.returncode = 0
        result = is_git_repo(str(tmp_path))
        assert result is True
```

```python
# BAD: Runs actual git command
def test_git_detection():
    subprocess.run(["git", "rev-parse", "--is-inside-work-tree"])

# GOOD: Mocks subprocess
def test_git_detection(tmp_path):
    with patch('subprocess.run') as mock:
        mock.return_value.returncode = 0
        result = is_git_repo(str(tmp_path))
        assert result is True
```

### 2. File system tests

Use `tmp_path` fixture for isolation:

```python
# BAD: Uses current directory
def test_config(tmp_path):
    Path("projects.conf").write_text("...")

# GOOD: Uses tmp_path
def test_config(tmp_path):
    (tmp_path / "projects.conf").write_text("...")
```

### 3. Config caching

Config is cached per-process. Clear cache between tests:

```python
def test_config_isolation(tmp_path):
    from txs.config import parse_config, invalidate_config_cache

    # First parse
    parse_config(tmp_path / "projects.conf")

    # Clear cache for next test
    invalidate_config_cache()

    # Second parse
    parse_config(tmp_path / "projects.conf")
```

## CI Integration

Tests run on GitHub Actions via `.github/workflows/ci.yml`. All tests must pass before merging.

## Adding New Tests

1. Create a test function or class in the appropriate test file
2. Add docstrings explaining what's being tested
3. Use `tmp_path` for file system tests
4. Mock external dependencies (tmux, git)
5. Test both success and error cases
6. Run locally before pushing: `pytest -v`

## References

- [pytest documentation](https://docs.pytest.org/)
- [pytest-mock documentation](https://pytest-mock.readthedocs.io/)
- [conftest.py fixtures](tests/conftest.py)
