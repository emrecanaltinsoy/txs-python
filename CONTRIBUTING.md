# Contributing to txs-python

Thanks for your interest in contributing! This document covers the essentials to get started.

## Prerequisites

- **Python 3.10+** (required by `pyproject.toml`)
- **uv** (recommended package manager)
- **tmux** (for testing sessions)
- **git** (for version control)

## Setup

```bash
# Clone the repo
git clone https://github.com/emrecanaltinsoy/txs-python.git
cd txs-python

# Create and activate virtual environment
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install -e .

# Install dev dependencies (pytest, ruff)
uv sync --group dev

# Run tests to verify setup
pytest
```

## Development Workflow

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_git.py

# Run with verbose output
pytest -v
```

### Code Style

This project uses **ruff** for linting and formatting:

```bash
# Check linting
ruff check src/

# Auto-fix formatting
ruff format src/

# Both
ruff check --fix src/ && ruff format src/ --check
```

Code is formatted with `ruff format` (Black-compatible). Follow the existing style.

### Making Changes

1. **Create a branch** from `main`:

   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** — keep them focused and well-tested.

3. **Add tests** for new functionality (see [Testing Guide](docs/testing.md)).

4. **Run tests and linting**:

   ```bash
   pytest && ruff check src/ && ruff format src/ --check
   ```

5. **Commit with conventional commits** (see below).

6. **Open a PR** on GitHub with a clear description.

## Testing

For comprehensive testing guidelines, patterns, and examples, see [the Testing Guide](docs/testing.md).

## Commit Messages

Use **conventional commits** format:

```text
<type>(<scope>): <subject>

<body> (optional, when "why" isn't obvious)
```

**Types:**

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation changes
- `test:` — test additions/changes
- `chore:` — maintenance tasks

**Examples:**

```text
feat(config): add max_depth option for nested repo scanning

fix(tui): prevent crash when session has no active window

docs(readme): clarify worktree removal behavior
```

## Documentation

- Update `README.md` for user-facing changes
- Add docstrings to new public functions
- Update `CONTRIBUTING.md` if adding new workflows

## Pull Requests

1. **One feature per PR** — keep changes focused
2. **Include tests** for new functionality
3. **Update documentation** as needed
4. **Reference issues** if applicable

## Questions?

- Open an issue for questions, bugs, or feature requests
- Check existing issues/PRs before creating duplicates

Thank you for contributing! 🚀
