"""Tests for telemetry/tui/_app.py.

TelemetryTranscriptsApp is a Textual App and most of its surface area requires a
running event loop (compose, on_mount, _refresh_data, etc.).  We test what is
genuinely reachable without mounting the app:

- Constructor state (attribute initialisation)
- Pure logic helpers: _refresh_tools_table key deduplication logic (key string
  building), _refresh_agents_table key building, _refresh_timeline row building,
  _refresh_tips_table key building, on_data_table_row_selected dispatch table
- Detail-router methods (_show_*_detail) with mocked push_screen
- action_switch_session — mocked transcript, verified push_screen call
- run_live is pragma: no cover, not tested here

Textual's App.__init__ requires no running event loop, so instantiation is safe.
The methods that call query_one() (which needs a mounted DOM) are tested via
mocking query_one to return suitable DataTable/widget stubs.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from telemetry.tui._app import TelemetryTranscriptsApp
from telemetry.tui._widgets import _DetailModal

from tests.telemetry_tests.shared_fixtures import (
    _make_agent_summary_tui,
    _make_event,
    _make_summary,
    _make_tip,
    _make_tool_stats,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(session_id=None, refresh=2.0, rules_path=None) -> TelemetryTranscriptsApp:
    """Instantiate TelemetryTranscriptsApp with all external deps patched."""
    with patch("telemetry.tui._app.TranscriptProvider"), \
         patch("telemetry.tui._app.load_rules", return_value={}):
        app = TelemetryTranscriptsApp(
            session_id=session_id,
            refresh=refresh,
            rules_path=rules_path,
        )
    return app


# ---------------------------------------------------------------------------
# Constructor state
# ---------------------------------------------------------------------------

class TestAppConstructorState(unittest.TestCase):
    def test_refresh_stored(self):
        app = _make_app(refresh=4.5)
        self.assertEqual(app._refresh, 4.5)

    def test_session_id_stored(self):
        app = _make_app(session_id="abc123")
        self.assertEqual(app._session_id, "abc123")

    def test_session_id_none_by_default(self):
        app = _make_app()
        self.assertIsNone(app._session_id)

    def test_session_file_initially_none(self):
        app = _make_app()
        self.assertIsNone(app._session_file)

    def test_all_events_initially_empty(self):
        app = _make_app()
        self.assertEqual(app._all_events, [])

    def test_all_agents_initially_empty(self):
        app = _make_app()
        self.assertEqual(app._all_agents, [])

    def test_tool_stats_list_initially_empty(self):
        app = _make_app()
        self.assertEqual(app._tool_stats_list, [])

    def test_tips_list_initially_empty(self):
        app = _make_app()
        self.assertEqual(app._tips_list, [])

    def test_last_event_count_initially_zero(self):
        app = _make_app()
        self.assertEqual(app._last_event_count, 0)

    def test_last_tool_stats_key_initially_empty(self):
        app = _make_app()
        self.assertEqual(app._last_tool_stats_key, "")

    def test_last_agents_key_initially_empty(self):
        app = _make_app()
        self.assertEqual(app._last_agents_key, "")

    def test_last_tips_key_initially_empty(self):
        app = _make_app()
        self.assertEqual(app._last_tips_key, "")

    def test_classify_engine_created(self):
        app = _make_app()
        self.assertIsNotNone(app._classify)

    def test_blame_engine_created(self):
        app = _make_app()
        self.assertIsNotNone(app._blame)

    def test_tips_engine_created(self):
        app = _make_app()
        self.assertIsNotNone(app._tips_engine)

    def test_css_class_attr(self):
        from telemetry.tui._widgets import APP_CSS
        self.assertEqual(TelemetryTranscriptsApp.CSS, APP_CSS)

    def test_title_class_attr(self):
        self.assertEqual(TelemetryTranscriptsApp.TITLE, "telemetry-transcripts")

    def test_bindings_include_q(self):
        keys = [b.key for b in TelemetryTranscriptsApp.BINDINGS]
        self.assertIn("q", keys)

    def test_bindings_include_s(self):
        keys = [b.key for b in TelemetryTranscriptsApp.BINDINGS]
        self.assertIn("s", keys)


# ---------------------------------------------------------------------------
# _refresh_tools_table — key dedup logic
# ---------------------------------------------------------------------------

class TestRefreshToolsTableDedup(unittest.TestCase):
    def _make_stub_tbl(self):
        tbl = MagicMock()
        tbl.clear = MagicMock()
        tbl.add_row = MagicMock()
        return tbl

    def test_skips_refresh_when_key_unchanged(self):
        app = _make_app()
        stat = _make_tool_stats("Bash")
        stat.cost = 0.05
        stat.count = 3
        stat.avoidable_count = 1
        app._tool_stats_list = [stat]

        # Build the key that will be produced on first call
        expected_key = f"Bash:{stat.count}:{stat.cost:.4f}:{stat.avoidable_count}"
        app._last_tool_stats_key = expected_key

        tbl = self._make_stub_tbl()
        with patch.object(app, "query_one", return_value=tbl):
            app._refresh_tools_table()
        tbl.clear.assert_not_called()

    def test_refreshes_when_key_changes(self):
        app = _make_app()
        stat = _make_tool_stats("Bash")
        stat.cost = 0.05
        stat.count = 3
        stat.avoidable_count = 1
        app._tool_stats_list = [stat]
        app._last_tool_stats_key = "old-key"

        tbl = self._make_stub_tbl()
        with patch.object(app, "query_one", return_value=tbl):
            app._refresh_tools_table()
        tbl.clear.assert_called_once()

    def test_adds_row_for_each_stat(self):
        app = _make_app()
        stats = [_make_tool_stats(name) for name in ("Bash", "Read", "Edit")]
        for s in stats:
            s.cost = 0.01
            s.count = 1
            s.avoidable_count = 0
        app._tool_stats_list = stats
        app._last_tool_stats_key = "stale"

        tbl = self._make_stub_tbl()
        with patch.object(app, "query_one", return_value=tbl):
            app._refresh_tools_table()
        self.assertEqual(tbl.add_row.call_count, 3)

    def test_empty_stats_list_clears_table_without_rows(self):
        app = _make_app()
        app._tool_stats_list = []
        app._last_tool_stats_key = "nonempty-key"

        tbl = self._make_stub_tbl()
        with patch.object(app, "query_one", return_value=tbl):
            app._refresh_tools_table()
        tbl.clear.assert_called_once()
        tbl.add_row.assert_not_called()

    def test_avoid_str_is_dash_when_zero(self):
        app = _make_app()
        stat = _make_tool_stats("Bash")
        stat.cost = 0.01
        stat.count = 2
        stat.avoidable_count = 0
        app._tool_stats_list = [stat]
        app._last_tool_stats_key = "stale"

        tbl = self._make_stub_tbl()
        with patch.object(app, "query_one", return_value=tbl):
            app._refresh_tools_table()
        row_args = tbl.add_row.call_args[0]
        self.assertEqual(row_args[4], "—")

    def test_avoid_str_is_count_when_nonzero(self):
        app = _make_app()
        stat = _make_tool_stats("Bash")
        stat.cost = 0.01
        stat.count = 5
        stat.avoidable_count = 3
        app._tool_stats_list = [stat]
        app._last_tool_stats_key = "stale"

        tbl = self._make_stub_tbl()
        with patch.object(app, "query_one", return_value=tbl):
            app._refresh_tools_table()
        row_args = tbl.add_row.call_args[0]
        self.assertEqual(row_args[4], "3")


# ---------------------------------------------------------------------------
# _refresh_agents_table — key dedup logic
# ---------------------------------------------------------------------------

class TestRefreshAgentsTableDedup(unittest.TestCase):
    def _make_stub_tbl(self):
        tbl = MagicMock()
        tbl.clear = MagicMock()
        tbl.add_row = MagicMock()
        return tbl

    def test_skips_refresh_when_key_unchanged(self):
        app = _make_app()
        agent = _make_agent_summary_tui()
        app._last_agents_key = f"{agent.agent_id}:{agent.total_tool_uses}"

        tbl = self._make_stub_tbl()
        with patch.object(app, "query_one", return_value=tbl):
            app._refresh_agents_table([agent])
        tbl.clear.assert_not_called()

    def test_refreshes_when_agent_list_changes(self):
        app = _make_app()
        agent = _make_agent_summary_tui()
        app._last_agents_key = "old-key"

        tbl = self._make_stub_tbl()
        with patch.object(app, "query_one", return_value=tbl):
            app._refresh_agents_table([agent])
        tbl.clear.assert_called_once()
        tbl.add_row.assert_called_once()

    def test_model_short_name_extracted(self):
        app = _make_app()
        agent = _make_agent_summary_tui()
        app._last_agents_key = "stale"

        tbl = self._make_stub_tbl()
        with patch.object(app, "query_one", return_value=tbl):
            app._refresh_agents_table([agent])
        row_args = tbl.add_row.call_args[0]
        # model_short should be the part after the last "/"
        model_short = agent.model.split("/")[-1]
        self.assertIn(model_short, row_args)

    def test_description_truncated_to_25_chars(self):
        app = _make_app()
        agent = _make_agent_summary_tui()
        agent = agent.__class__(
            **{**agent.__dict__, "description": "A" * 40}
        )
        app._last_agents_key = "stale"

        tbl = self._make_stub_tbl()
        with patch.object(app, "query_one", return_value=tbl):
            app._refresh_agents_table([agent])
        row_args = tbl.add_row.call_args[0]
        desc_arg = row_args[0]
        self.assertLessEqual(len(desc_arg), 25)

    def test_empty_agents_clears_table(self):
        app = _make_app()
        app._last_agents_key = "nonempty"

        tbl = self._make_stub_tbl()
        with patch.object(app, "query_one", return_value=tbl):
            app._refresh_agents_table([])
        tbl.clear.assert_called_once()
        tbl.add_row.assert_not_called()


# ---------------------------------------------------------------------------
# _refresh_tips_table — key dedup and display logic
# ---------------------------------------------------------------------------

class TestRefreshTipsTableDedup(unittest.TestCase):
    def _make_stubs(self):
        tbl = MagicMock()
        tbl.clear = MagicMock()
        tbl.add_row = MagicMock()
        empty_panel = MagicMock()
        empty_panel.update_empty = MagicMock()
        return tbl, empty_panel

    def _query_one_side_effect(self, tbl, empty_panel):
        def _qone(selector, widget_type=None):
            if selector == "#tips-table":
                return tbl
            if selector == "#tips-empty":
                return empty_panel
            return MagicMock()

        return _qone

    def test_skips_refresh_when_key_unchanged(self):
        app = _make_app()
        tip = _make_tip(severity="avoidable")
        expected_key = f"{tip.waste_reason}:{tip.count}:{tip.cost_impact:.4f}"
        app._last_tips_key = expected_key

        tbl, empty_panel = self._make_stubs()
        with patch.object(app, "query_one", side_effect=self._query_one_side_effect(tbl, empty_panel)):
            app._refresh_tips_table([tip])
        tbl.clear.assert_not_called()

    def test_shows_empty_panel_when_no_tips(self):
        app = _make_app()
        app._last_tips_key = "stale"

        tbl, empty_panel = self._make_stubs()
        with patch.object(app, "query_one", side_effect=self._query_one_side_effect(tbl, empty_panel)):
            app._refresh_tips_table([])
        self.assertFalse(tbl.display)
        self.assertTrue(empty_panel.display)
        empty_panel.update_empty.assert_called_once()

    def test_shows_table_and_hides_empty_when_tips_present(self):
        app = _make_app()
        app._last_tips_key = "stale"
        tip = _make_tip()

        tbl, empty_panel = self._make_stubs()
        with patch.object(app, "query_one", side_effect=self._query_one_side_effect(tbl, empty_panel)):
            app._refresh_tips_table([tip])
        self.assertTrue(tbl.display)
        self.assertFalse(empty_panel.display)

    def test_adds_row_per_tip(self):
        app = _make_app()
        app._last_tips_key = "stale"
        tips = [_make_tip(severity=s) for s in ("avoidable", "review")]

        tbl, empty_panel = self._make_stubs()
        with patch.object(app, "query_one", side_effect=self._query_one_side_effect(tbl, empty_panel)):
            app._refresh_tips_table(tips)
        self.assertEqual(tbl.add_row.call_count, 2)

    def test_avoidable_tip_uses_x_symbol(self):
        app = _make_app()
        app._last_tips_key = "stale"
        tip = _make_tip(severity="avoidable")

        tbl, empty_panel = self._make_stubs()
        with patch.object(app, "query_one", side_effect=self._query_one_side_effect(tbl, empty_panel)):
            app._refresh_tips_table([tip])
        sym = tbl.add_row.call_args[0][0]
        self.assertEqual(sym, "✗")

    def test_review_tip_uses_warning_symbol(self):
        app = _make_app()
        app._last_tips_key = "stale"
        tip = _make_tip(severity="review")

        tbl, empty_panel = self._make_stubs()
        with patch.object(app, "query_one", side_effect=self._query_one_side_effect(tbl, empty_panel)):
            app._refresh_tips_table([tip])
        sym = tbl.add_row.call_args[0][0]
        self.assertEqual(sym, "⚠")


# ---------------------------------------------------------------------------
# _refresh_timeline — row content
# ---------------------------------------------------------------------------

class TestRefreshTimeline(unittest.TestCase):
    def test_adds_row_for_each_tool_event(self):
        app = _make_app()
        events = [
            _make_event(tool_name="Bash", classification="productive"),
            _make_event(tool_name="Read", classification="neutral"),
        ]
        tbl = MagicMock()
        tbl.clear = MagicMock()
        tbl.add_row = MagicMock()
        with patch.object(app, "query_one", return_value=tbl):
            app._refresh_timeline(events)
        self.assertEqual(tbl.add_row.call_count, 2)

    def test_skips_non_tool_events(self):
        app = _make_app()
        events = [
            _make_event(event_type="text", tool_name=None),
            _make_event(tool_name="Bash", classification="productive"),
        ]
        tbl = MagicMock()
        tbl.clear = MagicMock()
        tbl.add_row = MagicMock()
        with patch.object(app, "query_one", return_value=tbl):
            app._refresh_timeline(events)
        self.assertEqual(tbl.add_row.call_count, 1)

    def test_fail_tag_set_when_success_false(self):
        app = _make_app()
        evt = _make_event(tool_name="Bash")
        evt = evt.__class__(**{**evt.__dict__, "success": False, "waste_reason": None})
        tbl = MagicMock()
        tbl.clear = MagicMock()
        tbl.add_row = MagicMock()
        with patch.object(app, "query_one", return_value=tbl):
            app._refresh_timeline([evt])
        row_args = tbl.add_row.call_args[0]
        tag = row_args[5]
        self.assertEqual(tag, "FAIL")

    def test_waste_tag_set_from_waste_reason(self):
        app = _make_app()
        evt = _make_event(tool_name="Bash")
        evt = evt.__class__(**{**evt.__dict__, "waste_reason": "bash-as-grep"})
        tbl = MagicMock()
        tbl.clear = MagicMock()
        tbl.add_row = MagicMock()
        with patch.object(app, "query_one", return_value=tbl):
            app._refresh_timeline([evt])
        row_args = tbl.add_row.call_args[0]
        tag = row_args[5]
        self.assertEqual(tag, "GREP")

    def test_clears_table_before_adding(self):
        app = _make_app()
        tbl = MagicMock()
        tbl.clear = MagicMock()
        tbl.add_row = MagicMock()
        with patch.object(app, "query_one", return_value=tbl):
            app._refresh_timeline([])
        tbl.clear.assert_called_once()


# ---------------------------------------------------------------------------
# Detail-router helpers (_show_*_detail)
# ---------------------------------------------------------------------------

class TestShowDetailMethods(unittest.TestCase):
    def test_show_timeline_detail_within_bounds(self):
        app = _make_app()
        evt = _make_event(tool_name="Bash")
        app._all_events = [evt]
        app.push_screen = MagicMock()
        app._show_timeline_detail(0)
        app.push_screen.assert_called_once()
        pushed = app.push_screen.call_args[0][0]
        self.assertIsInstance(pushed, _DetailModal)
        self.assertEqual(pushed._title, "Event Detail")

    def test_show_timeline_detail_out_of_bounds_does_not_push(self):
        app = _make_app()
        app._all_events = []
        app.push_screen = MagicMock()
        app._show_timeline_detail(0)
        app.push_screen.assert_not_called()

    def test_show_tools_detail_within_bounds(self):
        app = _make_app()
        stat = _make_tool_stats("Bash")
        stat.cost = 0.01
        stat.count = 1
        stat.avoidable_count = 0
        app._tool_stats_list = [stat]
        app._all_events = []
        app.push_screen = MagicMock()
        app._show_tools_detail(0)
        app.push_screen.assert_called_once()
        pushed = app.push_screen.call_args[0][0]
        self.assertEqual(pushed._title, "Tool Detail")

    def test_show_tools_detail_out_of_bounds_does_not_push(self):
        app = _make_app()
        app._tool_stats_list = []
        app.push_screen = MagicMock()
        app._show_tools_detail(0)
        app.push_screen.assert_not_called()

    def test_show_agents_detail_within_bounds(self):
        app = _make_app()
        agent = _make_agent_summary_tui()
        app._all_agents = [agent]
        app.push_screen = MagicMock()
        app._show_agents_detail(0)
        app.push_screen.assert_called_once()
        pushed = app.push_screen.call_args[0][0]
        self.assertEqual(pushed._title, "Agent Detail")

    def test_show_agents_detail_out_of_bounds_does_not_push(self):
        app = _make_app()
        app._all_agents = []
        app.push_screen = MagicMock()
        app._show_agents_detail(0)
        app.push_screen.assert_not_called()

    def test_show_tips_detail_within_bounds(self):
        app = _make_app()
        tip = _make_tip()
        app._tips_list = [tip]
        app.push_screen = MagicMock()
        app._show_tips_detail(0)
        app.push_screen.assert_called_once()
        pushed = app.push_screen.call_args[0][0]
        self.assertEqual(pushed._title, "Tip Detail")

    def test_show_tips_detail_out_of_bounds_does_not_push(self):
        app = _make_app()
        app._tips_list = []
        app.push_screen = MagicMock()
        app._show_tips_detail(0)
        app.push_screen.assert_not_called()


# ---------------------------------------------------------------------------
# on_data_table_row_selected dispatch
# ---------------------------------------------------------------------------

class TestOnDataTableRowSelected(unittest.TestCase):
    def _make_event_obj(self, table_id: str, cursor_row: int | None):
        from textual.widgets import DataTable
        event = MagicMock(spec=DataTable.RowSelected)
        event.data_table = MagicMock()
        event.data_table.id = table_id
        event.cursor_row = cursor_row
        return event

    def test_dispatches_to_timeline_handler(self):
        app = _make_app()
        app._show_timeline_detail = MagicMock()
        event = self._make_event_obj("timeline", 2)
        app.on_data_table_row_selected(event)
        app._show_timeline_detail.assert_called_once_with(2)

    def test_dispatches_to_tools_handler(self):
        app = _make_app()
        app._show_tools_detail = MagicMock()
        event = self._make_event_obj("tools-table", 1)
        app.on_data_table_row_selected(event)
        app._show_tools_detail.assert_called_once_with(1)

    def test_dispatches_to_agents_handler(self):
        app = _make_app()
        app._show_agents_detail = MagicMock()
        event = self._make_event_obj("agents-table", 0)
        app.on_data_table_row_selected(event)
        app._show_agents_detail.assert_called_once_with(0)

    def test_dispatches_to_tips_handler(self):
        app = _make_app()
        app._show_tips_detail = MagicMock()
        event = self._make_event_obj("tips-table", 3)
        app.on_data_table_row_selected(event)
        app._show_tips_detail.assert_called_once_with(3)

    def test_unknown_table_id_does_not_raise(self):
        app = _make_app()
        event = self._make_event_obj("unknown-table", 0)
        app.on_data_table_row_selected(event)  # should not raise

    def test_negative_row_index_returns_early(self):
        app = _make_app()
        app._show_timeline_detail = MagicMock()
        event = self._make_event_obj("timeline", -1)
        app.on_data_table_row_selected(event)
        app._show_timeline_detail.assert_not_called()

    def test_none_cursor_row_returns_early(self):
        app = _make_app()
        app._show_timeline_detail = MagicMock()
        event = self._make_event_obj("timeline", None)
        app.on_data_table_row_selected(event)
        app._show_timeline_detail.assert_not_called()


# ---------------------------------------------------------------------------
# action_switch_session
# ---------------------------------------------------------------------------

class TestActionSwitchSession(unittest.TestCase):
    def test_notify_when_no_sessions(self):
        app = _make_app()
        app._transcript.get_sessions.return_value = []
        app.notify = MagicMock()
        app.push_screen = MagicMock()
        app.action_switch_session()
        app.notify.assert_called_once()
        app.push_screen.assert_not_called()

    def test_push_screen_with_session_picker_when_sessions_exist(self):
        from telemetry.tui._widgets import SessionPickerScreen
        app = _make_app()
        sessions = [_make_summary(session_id="s001")]
        app._transcript.get_sessions.return_value = sessions
        app.push_screen = MagicMock()
        app.action_switch_session()
        app.push_screen.assert_called_once()
        picker = app.push_screen.call_args[0][0]
        self.assertIsInstance(picker, SessionPickerScreen)

    def test_on_dismiss_updates_session_id(self):
        app = _make_app()
        sessions = [_make_summary(session_id="s002")]
        app._transcript.get_sessions.return_value = sessions
        app._transcript.find_session_file.return_value = None
        captured_callback = {}

        def fake_push_screen(screen, callback=None):
            captured_callback["fn"] = callback

        app.push_screen = fake_push_screen
        app._refresh_data = MagicMock()
        app.action_switch_session()

        # Simulate the picker dismissing with a session id
        captured_callback["fn"]("s002")
        self.assertEqual(app._session_id, "s002")
        app._refresh_data.assert_called_once()

    def test_on_dismiss_with_empty_string_does_not_update(self):
        app = _make_app()
        sessions = [_make_summary(session_id="s003")]
        app._transcript.get_sessions.return_value = sessions
        app._session_id = "original"
        captured_callback = {}

        def fake_push_screen(screen, callback=None):
            captured_callback["fn"] = callback

        app.push_screen = fake_push_screen
        app._refresh_data = MagicMock()
        app.action_switch_session()

        captured_callback["fn"]("")  # dismissed with empty string
        self.assertEqual(app._session_id, "original")
        app._refresh_data.assert_not_called()

    def test_on_dismiss_resets_last_event_count(self):
        app = _make_app()
        sessions = [_make_summary(session_id="s004")]
        app._transcript.get_sessions.return_value = sessions
        app._transcript.find_session_file.return_value = None
        app._last_event_count = 99
        captured_callback = {}

        def fake_push_screen(screen, callback=None):
            captured_callback["fn"] = callback

        app.push_screen = fake_push_screen
        app._refresh_data = MagicMock()
        app.action_switch_session()
        captured_callback["fn"]("s004")
        self.assertEqual(app._last_event_count, 0)


# ---------------------------------------------------------------------------
# compose() — a plain generator (no context manager), so it runs without a
# mounted app and the widget/id wiring is directly assertable.
# ---------------------------------------------------------------------------

class TestAppCompose(unittest.TestCase):
    def _ids(self):
        return [getattr(w, "id", None) for w in _make_app().compose()]

    def test_yields_expected_widget_ids_in_order(self):
        self.assertEqual(
            self._ids(),
            ["header", "tools-table", "agents-table", "timeline",
             "tips-table", "tips-empty", "footer-info", None],
        )

    def test_yields_four_data_tables(self):
        from textual.widgets import DataTable

        tables = [w for w in _make_app().compose() if isinstance(w, DataTable)]
        self.assertEqual(len(tables), 4)

    def test_header_is_header_panel(self):
        from telemetry.tui._widgets import HeaderPanel

        first = next(iter(_make_app().compose()))
        self.assertIsInstance(first, HeaderPanel)

    def test_ids_are_unique_where_set(self):
        ids = [i for i in self._ids() if i is not None]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
