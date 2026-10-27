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


class TestKillSessionInplace:
    def _patch(self, monkeypatch, *, exists=True, inside=False, current=""):
        import subprocess

        from txs import tmux

        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            stdout = current + "\n" if cmd[:2] == ["tmux", "display-message"] else ""
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

        monkeypatch.setattr(tmux, "session_exists", lambda name: exists)
        monkeypatch.setattr(tmux, "is_inside_tmux", lambda: inside)
        monkeypatch.setattr(tmux.subprocess, "run", fake_run)
        return calls

    def test_kills_session_outside_tmux(self, monkeypatch):
        from txs.tmux import kill_session_inplace

        calls = self._patch(monkeypatch)
        kill_session_inplace("work")
        assert calls == [["tmux", "kill-session", "-t", "=work"]]

    def test_missing_session_is_noop(self, monkeypatch):
        from txs.tmux import kill_session_inplace

        calls = self._patch(monkeypatch, exists=False)
        kill_session_inplace("gone")
        assert calls == []

    def test_switches_client_when_killing_current_session(self, monkeypatch):
        from txs.tmux import kill_session_inplace

        calls = self._patch(monkeypatch, inside=True, current="work")
        kill_session_inplace("work")
        assert ["tmux", "switch-client", "-l"] in calls
        assert calls[-1] == ["tmux", "kill-session", "-t", "=work"]

    def test_no_switch_when_other_session_is_current(self, monkeypatch):
        from txs.tmux import kill_session_inplace

        calls = self._patch(monkeypatch, inside=True, current="other")
        kill_session_inplace("work")
        assert not any("switch-client" in c for c in calls)
        assert calls[-1] == ["tmux", "kill-session", "-t", "=work"]
