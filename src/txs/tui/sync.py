"""TUI refresh orchestration — one tmux fetch and settings read per cycle."""

from __future__ import annotations

from dataclasses import dataclass

from txs.config import TuiSettingsView, load_tui_settings, reload_config_if_changed
from txs.git import clear_repo_caches
from txs.tmux import TmuxSnapshot


@dataclass(frozen=True)
class TuiRefreshBundle:
    snap: TmuxSnapshot
    settings: TuiSettingsView


def maybe_reload_config() -> None:
    """Invalidate cached projects.conf only when the file changed on disk."""
    reload_config_if_changed()


def fetch_refresh_bundle() -> TuiRefreshBundle:
    clear_repo_caches()
    return TuiRefreshBundle(
        snap=TmuxSnapshot.fetch(),
        settings=load_tui_settings(),
    )
