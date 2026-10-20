"""Theme picker and persistence for the TUI."""

from __future__ import annotations

from textual.command import CommandInput, CommandPalette
from textual.events import Mount
from textual.theme import Theme, ThemeProvider
from textual.widgets import Input

from txs.config import set_txs_setting

TUI_THEME_SETTING = "tui_theme"


class TxsThemeCommandPalette(CommandPalette):
    """Theme command palette that opens filtered to the current theme."""

    def __init__(self, initial_theme: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._initial_theme = initial_theme

    def _on_mount(self, event: Mount) -> None:
        super()._on_mount(event)
        if not self._initial_theme:
            return
        command_input = self.query_one(CommandInput)
        with self.prevent(Input.Changed):
            command_input.value = self._initial_theme
        self._gather_commands(self._initial_theme)


def apply_saved_theme(app, setting_key: str = TUI_THEME_SETTING) -> None:
    """Set app theme from config when the theme name is registered."""
    from txs.config import get_txs_setting

    saved = get_txs_setting(setting_key).strip()
    if saved and saved in app.available_themes:
        app.theme = saved


def persist_theme(theme: Theme) -> None:
    from txs.config import get_txs_setting

    if get_txs_setting(TUI_THEME_SETTING) == theme.name:
        return
    set_txs_setting(TUI_THEME_SETTING, theme.name)


def open_theme_palette(app) -> None:
    app.push_screen(
        TxsThemeCommandPalette(
            app.theme,
            providers=[ThemeProvider],
            placeholder="Search for themes…",
        ),
    )
