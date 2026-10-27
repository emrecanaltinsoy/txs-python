"""Tests for the TUI kill-confirmation modal (headless Textual, no tmux)."""

import asyncio

from textual.app import App

from txs.tui.app import ConfirmKillScreen


def _confirm(keys: list[str]) -> list:
    """Open ConfirmKillScreen, press keys, return dismiss results."""
    results: list = []

    class Host(App):
        def on_mount(self) -> None:
            self.push_screen(ConfirmKillScreen("demo"), results.append)

    async def run() -> None:
        async with Host().run_test() as pilot:
            await pilot.pause()
            for key in keys:
                await pilot.press(key)
            await pilot.pause()

    asyncio.run(run())
    return results


class TestConfirmKillScreen:
    def test_y_confirms(self):
        assert _confirm(["y"]) == [True]

    def test_capital_y_is_not_confirm(self):
        # Only lowercase 'y' confirms; anything else is No.
        assert _confirm(["Y"]) == [False]

    def test_n_cancels(self):
        assert _confirm(["n"]) == [False]

    def test_enter_defaults_to_no(self):
        assert _confirm(["enter"]) == [False]

    def test_escape_defaults_to_no(self):
        assert _confirm(["escape"]) == [False]

    def test_other_key_defaults_to_no(self):
        assert _confirm(["x"]) == [False]
