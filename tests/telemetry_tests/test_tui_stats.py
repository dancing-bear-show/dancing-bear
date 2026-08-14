"""Tests for telemetry/tui/_stats.py.

Tests cover _StatsRenderer.build() (both compact and panel paths, including
waiting/error states) and print_summary() (driven with patched
TranscriptProvider, capturing stdout via contextlib.redirect_stdout).
run_stats() is marked pragma: no cover and is not tested.
"""
from __future__ import annotations

import contextlib
import importlib
import io
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from rich.panel import Panel
from rich.text import Text

from telemetry.blame import BlameEngine
from telemetry.classify import ClassifyEngine
from telemetry.tui._stats import _StatsRenderer, print_summary

from tests.telemetry_tests.shared_fixtures import (
    TempProjectsDirMixin,
    _write_jsonl,
    make_assistant_record,
    make_user_record,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_renderer(
    session_id: str | None = None,
    compact: bool = False,
    transcript: object | None = None,
) -> _StatsRenderer:
    """Build a _StatsRenderer with stub engines and optional transcript mock."""
    if transcript is None:
        transcript = MagicMock()
        transcript.get_current_session_id.return_value = None
        transcript.find_session_file.return_value = None
    return _StatsRenderer(
        session_id=session_id,
        compact=compact,
        classify_engine=ClassifyEngine({}),
        blame_engine=BlameEngine({}),
        transcript=transcript,
    )


# ---------------------------------------------------------------------------
# _StatsRenderer.__init__ state
# ---------------------------------------------------------------------------

class TestStatsRendererInit(unittest.TestCase):
    def test_compact_flag_stored(self):
        r = _make_renderer(compact=True)
        self.assertTrue(r.compact)

    def test_compact_false_by_default(self):
        r = _make_renderer(compact=False)
        self.assertFalse(r.compact)

    def test_resolved_session_id_none_when_not_provided_and_no_current(self):
        r = _make_renderer(session_id=None)
        self.assertIsNone(r.resolved_session_id)

    def test_resolved_session_id_uses_provided_value(self):
        t = MagicMock()
        t.find_session_file.return_value = Path("/nonexistent/fake.jsonl")
        r = _make_renderer(session_id="given-id", transcript=t)
        self.assertEqual(r.resolved_session_id, "given-id")

    def test_resolved_session_id_falls_back_to_current(self):
        t = MagicMock()
        t.get_current_session_id.return_value = "discovered"
        t.find_session_file.return_value = None
        r = _make_renderer(session_id=None, transcript=t)
        self.assertEqual(r.resolved_session_id, "discovered")

    def test_session_file_resolved_when_session_id_given(self):
        fake_path = Path("/nonexistent/fake.jsonl")
        t = MagicMock()
        t.find_session_file.return_value = fake_path
        r = _make_renderer(session_id="sid", transcript=t)
        self.assertEqual(r.session_file, fake_path)
        t.find_session_file.assert_called_once_with("sid")

    def test_session_file_none_when_no_session_id(self):
        r = _make_renderer(session_id=None)
        self.assertIsNone(r.session_file)


# ---------------------------------------------------------------------------
# _StatsRenderer.build — waiting state (no session)
# ---------------------------------------------------------------------------

class TestStatsRendererBuildWaiting(unittest.TestCase):
    def test_returns_panel_when_no_session_file(self):
        r = _make_renderer()
        result = r.build()
        self.assertIsInstance(result, Panel)

    def test_waiting_panel_has_dim_border(self):
        r = _make_renderer()
        result = r.build()
        self.assertIsInstance(result, Panel)
        self.assertEqual(result.border_style, "dim")

    def test_waiting_text_is_text_instance(self):
        r = _make_renderer()
        result = r.build()
        # The Panel's renderable should be a Rich Text
        self.assertIsInstance(result.renderable, Text)

    def test_resolve_session_called_on_build(self):
        t = MagicMock()
        t.get_current_session_id.return_value = None
        t.find_session_file.return_value = None
        r = _StatsRenderer(
            session_id=None,
            compact=False,
            classify_engine=ClassifyEngine({}),
            blame_engine=BlameEngine({}),
            transcript=t,
        )
        r.build()
        t.get_current_session_id.assert_called()


# ---------------------------------------------------------------------------
# _StatsRenderer.build — lazy session discovery
# ---------------------------------------------------------------------------

class TestStatsRendererBuildLazyDiscovery(unittest.TestCase):
    def test_resolves_session_id_on_build_when_initially_none(self):
        t = MagicMock()
        t.get_current_session_id.return_value = None
        t.find_session_file.return_value = None
        r = _StatsRenderer(
            session_id=None,
            compact=False,
            classify_engine=ClassifyEngine({}),
            blame_engine=BlameEngine({}),
            transcript=t,
        )
        r.build()
        # Should have tried to discover the session
        t.get_current_session_id.assert_called()

    def test_finds_session_file_when_session_id_becomes_known(self):
        fake_path = Path("/nonexistent/some.jsonl")
        t = MagicMock()
        t.get_current_session_id.return_value = "newly-found"
        t.find_session_file.return_value = fake_path
        t.parse_session_with_agents.return_value = ([], [])
        r = _StatsRenderer(
            session_id=None,
            compact=False,
            classify_engine=ClassifyEngine({}),
            blame_engine=BlameEngine({}),
            transcript=t,
        )
        r.build()
        t.find_session_file.assert_called_with("newly-found")


# ---------------------------------------------------------------------------
# _StatsRenderer.build — error state (parse failure)
# ---------------------------------------------------------------------------

class TestStatsRendererBuildError(unittest.TestCase):
    def test_returns_red_panel_on_parse_exception(self):
        fake_path = Path("/nonexistent/bad.jsonl")
        t = MagicMock()
        t.get_current_session_id.return_value = "err-session"
        t.find_session_file.return_value = fake_path
        t.parse_session_with_agents.side_effect = OSError("disk error")
        r = _StatsRenderer(
            session_id="err-session",
            compact=False,
            classify_engine=ClassifyEngine({}),
            blame_engine=BlameEngine({}),
            transcript=t,
        )
        r.session_file = fake_path
        result = r.build()
        self.assertIsInstance(result, Panel)
        self.assertEqual(result.border_style, "red")


# ---------------------------------------------------------------------------
# _StatsRenderer.build — happy path (panel mode)
# ---------------------------------------------------------------------------

class TestStatsRendererBuildPanel(TempProjectsDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        proj = self.project_dir("testproj")
        records = [
            make_assistant_record(session_id="s1", input_tokens=200, output_tokens=100),
            make_user_record(session_id="s1"),
        ]
        self.session_file = _write_jsonl(proj, "s1.jsonl", records)
        self.provider.find_session_file = MagicMock(return_value=self.session_file)
        self.provider.get_current_session_id = MagicMock(return_value="s1")

    def test_build_panel_mode_returns_panel(self):
        r = _StatsRenderer(
            session_id="s1",
            compact=False,
            classify_engine=ClassifyEngine({}),
            blame_engine=BlameEngine({}),
            transcript=self.provider,
        )
        result = r.build()
        self.assertIsInstance(result, Panel)

    def test_build_compact_mode_returns_text(self):
        r = _StatsRenderer(
            session_id="s1",
            compact=True,
            classify_engine=ClassifyEngine({}),
            blame_engine=BlameEngine({}),
            transcript=self.provider,
        )
        result = r.build()
        self.assertIsInstance(result, Text)


# ---------------------------------------------------------------------------
# print_summary — happy path
# ---------------------------------------------------------------------------

class TestPrintSummaryHappyPath(TempProjectsDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        proj = self.project_dir("myproj")
        records = [
            make_assistant_record(session_id="psess", input_tokens=500, output_tokens=200),
            make_user_record(session_id="psess"),
        ]
        self.session_file = _write_jsonl(proj, "psess.jsonl", records)

    def test_print_summary_outputs_session_header(self):
        # Rich's Console resolves sys.stdout at write time, so redirect_stdout
        # does capture its output — no Console patch needed here.
        buf = io.StringIO()
        with patch("telemetry.tui._stats.TranscriptProvider") as MockProv:
            inst = MockProv.return_value
            inst.get_current_session_id.return_value = "psess"
            inst.find_session_file.return_value = self.session_file
            inst.parse_session_with_agents.return_value = ([], [])
            with contextlib.redirect_stdout(buf):
                print_summary(session_id="psess")
        output = buf.getvalue()
        # Assert on the rendered session line, not just the word "Session":
        # the id is what proves the requested session reached the renderer.
        self.assertIn("Session: psess", output)
        self.assertIn("Timeline", output)

    def test_print_summary_with_rich_console_capture(self):
        """Drive print_summary with a patched Console to capture Rich output."""
        buf = io.StringIO()
        from rich.console import Console
        fake_console = Console(file=buf, width=120, highlight=False)

        with patch("telemetry.tui._stats.TranscriptProvider") as MockProv, \
             patch("telemetry.tui._stats.Console", return_value=fake_console):
            inst = MockProv.return_value
            inst.get_current_session_id.return_value = "psess"
            inst.find_session_file.return_value = self.session_file
            inst.parse_session_with_agents.return_value = ([], [])
            print_summary(session_id="psess")

        output = buf.getvalue()
        self.assertIn("Session", output)

    def test_print_summary_uses_provided_session_id(self):
        buf = io.StringIO()
        from rich.console import Console
        fake_console = Console(file=buf, width=120, highlight=False)

        with patch("telemetry.tui._stats.TranscriptProvider") as MockProv, \
             patch("telemetry.tui._stats.Console", return_value=fake_console):
            inst = MockProv.return_value
            inst.find_session_file.return_value = self.session_file
            inst.parse_session_with_agents.return_value = ([], [])
            print_summary(session_id="psess")
            # find_session_file should have been called with our session id
            inst.find_session_file.assert_called_once_with("psess")


# ---------------------------------------------------------------------------
# print_summary — sad paths
# ---------------------------------------------------------------------------

class TestPrintSummarySadPaths(unittest.TestCase):
    def _capture(self, session_id=None, mock_setup=None):
        buf = io.StringIO()
        from rich.console import Console
        fake_console = Console(file=buf, width=120, highlight=False)
        with patch("telemetry.tui._stats.TranscriptProvider") as MockProv, \
             patch("telemetry.tui._stats.Console", return_value=fake_console):
            inst = MockProv.return_value
            if mock_setup:
                mock_setup(inst)
            print_summary(session_id=session_id)
        return buf.getvalue()

    def test_no_active_session_prints_error(self):
        def setup(inst):
            inst.get_current_session_id.return_value = None
        output = self._capture(session_id=None, mock_setup=setup)
        self.assertIn("No active session", output)

    def test_session_file_not_found_prints_error(self):
        def setup(inst):
            inst.find_session_file.return_value = None
        output = self._capture(session_id="missing-id", mock_setup=setup)
        self.assertIn("Session file not found", output)

    def test_no_session_returns_early_without_parsing(self):
        with patch("telemetry.tui._stats.TranscriptProvider") as MockProv, \
             patch("telemetry.tui._stats.Console"):
            inst = MockProv.return_value
            inst.get_current_session_id.return_value = None
            print_summary(session_id=None)
            inst.parse_session_with_agents.assert_not_called()

    def test_missing_file_returns_early_without_parsing(self):
        with patch("telemetry.tui._stats.TranscriptProvider") as MockProv, \
             patch("telemetry.tui._stats.Console"):
            inst = MockProv.return_value
            inst.find_session_file.return_value = None
            print_summary(session_id="ghost-session")
            inst.parse_session_with_agents.assert_not_called()


# ---------------------------------------------------------------------------
# telemetry.tui lazy __getattr__ — routes names to the three submodules and
# raises AttributeError for anything else.
# ---------------------------------------------------------------------------

class TestTuiLazyGetattr(unittest.TestCase):
    # The submodules are reached via importlib rather than
    # `from telemetry.tui import _widgets`, so each assertion compares the
    # lazily-resolved attribute against an object obtained WITHOUT going
    # through __getattr__. Asserting against `tui._widgets.HeaderPanel` would
    # route both sides through the code under test and pass even if the lazy
    # routing were completely broken.
    def test_textual_export_resolves_to_widgets_module(self):
        import telemetry.tui as tui

        widgets = importlib.import_module("telemetry.tui._widgets")
        self.assertIs(tui.HeaderPanel, widgets.HeaderPanel)

    def test_app_css_resolves(self):
        import telemetry.tui as tui

        self.assertIsInstance(tui.APP_CSS, str)

    def test_stats_export_resolves_to_stats_module(self):
        import telemetry.tui as tui

        stats = importlib.import_module("telemetry.tui._stats")
        self.assertIs(tui.print_summary, stats.print_summary)
        self.assertIs(tui.run_stats, stats.run_stats)

    def test_app_export_resolves_to_app_module(self):
        import telemetry.tui as tui

        app = importlib.import_module("telemetry.tui._app")
        self.assertIs(tui.run_live, app.run_live)
        self.assertIs(tui.TelemetryTranscriptsApp, app.TelemetryTranscriptsApp)

    def test_unknown_name_raises_attribute_error(self):
        import telemetry.tui as tui

        with self.assertRaises(AttributeError) as ctx:
            tui.definitely_not_a_real_export
        self.assertIn("definitely_not_a_real_export", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
