"""Tests for tmux helpers (no tmux subprocess required)."""

from txs.tmux import AgentInfo, TmuxSnapshot


class TestTmuxSnapshotWindowForPath:
    def _snap(self, locations: dict[str, list[tuple[str, str]]]) -> TmuxSnapshot:
        return TmuxSnapshot(
            sessions=("s1",),
            windows_by_session={"s1": ["main"]},
            agents=[],
            pane_locations=locations,
        )

    def test_exact_path_match(self):
        snap = self._snap({"s1": [("2", "/repo/wt-main")]})
        assert snap.window_for_path("s1", "/repo/wt-main") == "2"

    def test_prefix_path_match(self):
        snap = self._snap({"s1": [("3", "/repo/wt-main/src")]})
        assert snap.window_for_path("s1", "/repo/wt-main") == "3"

    def test_no_match(self):
        snap = self._snap({"s1": [("1", "/other")]})
        assert snap.window_for_path("s1", "/repo/wt-main") is None

    def test_agents_preserved(self):
        agent = AgentInfo(
            session="s1",
            pane_id="%1",
            pane_index="0",
            title="pi",
            command="pi",
        )
        snap = TmuxSnapshot(
            sessions=("s1",),
            windows_by_session={},
            agents=[agent],
        )
        assert snap.agents == [agent]
