"""Shared pytest fixtures."""

from pathlib import Path

import pytest


@pytest.fixture()
def tmp_config_dir(tmp_path: Path) -> Path:
    """Return a temp dir pre-seeded with an empty projects.conf."""
    (tmp_path / "projects.conf").touch()
    return tmp_path


@pytest.fixture()
def projects_conf(tmp_path: Path):
    """Helper: write content to a temp projects.conf and return its Path."""

    def _write(content: str) -> Path:
        p = tmp_path / "projects.conf"
        p.write_text(content)
        return p

    return _write
