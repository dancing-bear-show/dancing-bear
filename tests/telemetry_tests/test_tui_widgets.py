"""Tests for telemetry/tui/_widgets.py.

Tests cover HeaderPanel, TipsPanel, FooterInfo, _DetailModal, and
SessionPickerScreen — focusing on update logic and compose output rather than
mounting a full Textual event loop.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from telemetry.tui._widgets import (
    APP_CSS,
    _DetailModal,
    FooterInfo,
    HeaderPanel,
    SessionPickerScreen,
    TipsPanel,
)

from tests.telemetry_tests.shared_fixtures import _make_summary


# ---------------------------------------------------------------------------
# APP_CSS constant
# ---------------------------------------------------------------------------

class TestAppCssConstant(unittest.TestCase):
    def test_css_is_non_empty_string(self):
        self.assertIsInstance(APP_CSS, str)
        self.assertGreater(len(APP_CSS), 0)

    def test_css_contains_header_panel_rule(self):
        self.assertIn("HeaderPanel", APP_CSS)

    def test_css_contains_footer_rule(self):
        self.assertIn("FooterInfo", APP_CSS)

    def test_css_contains_tips_panel_rule(self):
        self.assertIn("TipsPanel", APP_CSS)

    def test_css_contains_session_picker_rule(self):
        self.assertIn("SessionPickerScreen", APP_CSS)


# ---------------------------------------------------------------------------
# HeaderPanel.update_summary
# ---------------------------------------------------------------------------

class TestHeaderPanelUpdateSummary(unittest.TestCase):
    def test_update_called_with_rendered_text(self):
        panel = HeaderPanel()
        rendered = "[bold]Session: abc123[/]"
        with patch("telemetry.tui._widgets.HeaderPanel.update") as mock_update, \
             patch("telemetry.tui._renderers._render_header_text", return_value=rendered) as mock_render:
            summary = _make_summary()
            panel.update_summary(summary)
            mock_render.assert_called_once_with(summary)
            mock_update.assert_called_once_with(rendered)

    def test_update_summary_passes_correct_summary_to_renderer(self):
        panel = HeaderPanel()
        summary = _make_summary(session_id="deadbeef1234abcd", total_cost=0.99)
        captured: dict = {}
        with patch(
            "telemetry.tui._renderers._render_header_text",
            side_effect=lambda s: captured.update({"s": s}) or "x",
        ), patch("telemetry.tui._widgets.HeaderPanel.update"):
            panel.update_summary(summary)
        self.assertIs(captured["s"], summary)

    def test_update_summary_happy_path_does_not_raise(self):
        panel = HeaderPanel()
        summary = _make_summary()
        with patch("telemetry.tui._widgets.HeaderPanel.update"), \
             patch("telemetry.tui._renderers._render_header_text", return_value="ok"):
            panel.update_summary(summary)


# ---------------------------------------------------------------------------
# TipsPanel.update_empty
# ---------------------------------------------------------------------------

class TestTipsPanelUpdateEmpty(unittest.TestCase):
    def _get_update_arg(self) -> str:
        panel = TipsPanel()
        with patch("telemetry.tui._widgets.TipsPanel.update") as mock_update:
            panel.update_empty()
            mock_update.assert_called_once()
            return mock_update.call_args[0][0]

    def test_update_called_once(self):
        panel = TipsPanel()
        with patch("telemetry.tui._widgets.TipsPanel.update") as mock_update:
            panel.update_empty()
            mock_update.assert_called_once()

    def test_message_contains_no_tips(self):
        arg = self._get_update_arg()
        self.assertIn("No tips", arg)

    def test_message_contains_clean(self):
        arg = self._get_update_arg()
        self.assertIn("clean", arg.lower())

    def test_message_uses_dim_markup(self):
        arg = self._get_update_arg()
        self.assertIn("[dim]", arg)


# ---------------------------------------------------------------------------
# FooterInfo.update_info
# ---------------------------------------------------------------------------

class TestFooterInfoUpdateInfo(unittest.TestCase):
    def _call(self, **overrides) -> str:
        defaults = dict(session_id="abcdef123456", event_count=42, refresh=5.0, estimated=False)
        defaults.update(overrides)
        panel = FooterInfo()
        with patch("telemetry.tui._widgets.FooterInfo.update") as mock_update:
            panel.update_info(**defaults)
            mock_update.assert_called_once()
            return mock_update.call_args[0][0]

    def test_session_id_truncated_to_12_chars(self):
        result = self._call(session_id="abcdef123456789xyz")
        self.assertIn("abcdef123456", result)
        self.assertNotIn("789xyz", result)

    def test_event_count_shown(self):
        result = self._call(event_count=99)
        self.assertIn("99", result)

    def test_refresh_rate_shown(self):
        result = self._call(refresh=3.0)
        self.assertIn("3.0", result)

    def test_estimated_flag_shown_when_true(self):
        result = self._call(estimated=True)
        self.assertIn("[estimated]", result)

    def test_estimated_flag_absent_when_false(self):
        result = self._call(estimated=False)
        self.assertNotIn("[estimated]", result)

    def test_key_hint_tab_included(self):
        result = self._call()
        self.assertIn("Tab", result)

    def test_key_hint_quit_included(self):
        result = self._call()
        self.assertIn("quit", result)

    def test_key_hint_switch_included(self):
        result = self._call()
        self.assertIn("switch", result)

    def test_short_session_id_not_over_truncated(self):
        result = self._call(session_id="abc123")
        self.assertIn("abc123", result)


# ---------------------------------------------------------------------------
# _DetailModal
# ---------------------------------------------------------------------------

class TestDetailModalInit(unittest.TestCase):
    def test_stores_title(self):
        modal = _DetailModal("My Title", "some content")
        self.assertEqual(modal._title, "My Title")

    def test_stores_content(self):
        modal = _DetailModal("My Title", "some content")
        self.assertEqual(modal._content, "some content")

    def test_bindings_include_escape(self):
        binding_keys = [b.key for b in _DetailModal.BINDINGS]
        self.assertIn("escape", binding_keys)

    def test_bindings_include_enter(self):
        binding_keys = [b.key for b in _DetailModal.BINDINGS]
        self.assertIn("enter", binding_keys)

    def test_empty_title_stored(self):
        modal = _DetailModal("", "content")
        self.assertEqual(modal._title, "")

    def test_empty_content_stored(self):
        modal = _DetailModal("Title", "")
        self.assertEqual(modal._content, "")

    def test_escape_action_is_dismiss(self):
        for b in _DetailModal.BINDINGS:
            if b.key == "escape":
                self.assertEqual(b.action, "dismiss")
                return
        self.fail("escape binding not found")

    def test_enter_action_is_dismiss(self):
        for b in _DetailModal.BINDINGS:
            if b.key == "enter":
                self.assertEqual(b.action, "dismiss")
                return
        self.fail("enter binding not found")


# ---------------------------------------------------------------------------
# SessionPickerScreen
# ---------------------------------------------------------------------------

class TestSessionPickerScreenInit(unittest.TestCase):
    def test_stores_sessions(self):
        sessions = [_make_summary(session_id=f"s{i:012d}") for i in range(3)]
        screen = SessionPickerScreen(sessions)
        self.assertEqual(screen._sessions, sessions)

    def test_empty_sessions_stored(self):
        screen = SessionPickerScreen([])
        self.assertEqual(screen._sessions, [])

    def test_binding_includes_escape(self):
        binding_keys = [b.key for b in SessionPickerScreen.BINDINGS]
        self.assertIn("escape", binding_keys)

    def test_stores_large_session_list(self):
        sessions = [_make_summary(session_id=f"{i:016x}") for i in range(60)]
        screen = SessionPickerScreen(sessions)
        self.assertEqual(len(screen._sessions), 60)

    def test_action_dismiss_modal_calls_dismiss_with_empty_string(self):
        screen = SessionPickerScreen([])
        screen.dismiss = MagicMock()
        screen.action_dismiss_modal()
        screen.dismiss.assert_called_once_with("")

    def test_escape_action_name(self):
        for b in SessionPickerScreen.BINDINGS:
            if b.key == "escape":
                self.assertEqual(b.action, "dismiss_modal")
                return
        self.fail("escape binding not found")


# ---------------------------------------------------------------------------
# compose() output — generators run without a mounted DOM, so the label
# formatting inside them is directly assertable.
# ---------------------------------------------------------------------------

class TestSessionPickerCompose(unittest.TestCase):
    def _options(self, sessions):
        widgets = list(SessionPickerScreen(sessions).compose())
        self.assertEqual(len(widgets), 1)
        return list(widgets[0]._options)

    def test_yields_one_option_per_session(self):
        sessions = [_make_summary(session_id=f"{i:016x}") for i in range(3)]
        self.assertEqual(len(self._options(sessions)), 3)

    def test_caps_option_list_at_fifty(self):
        sessions = [_make_summary(session_id=f"{i:016x}") for i in range(60)]
        self.assertEqual(len(self._options(sessions)), 50)

    def test_option_id_is_full_session_id(self):
        opts = self._options([_make_summary(session_id="abcdef0123456789")])
        self.assertEqual(opts[0].id, "abcdef0123456789")

    def test_label_truncates_session_id_to_twelve_chars(self):
        opts = self._options([_make_summary(session_id="abcdef0123456789")])
        label = str(opts[0].prompt)
        self.assertIn("abcdef012345", label)
        self.assertNotIn("abcdef0123456789", label)

    def test_label_includes_formatted_cost(self):
        opts = self._options([_make_summary(total_cost=1.2345)])
        self.assertIn("$1.23", str(opts[0].prompt))

    def test_label_keeps_last_forty_chars_of_project_path(self):
        long_path = "/a" * 60
        opts = self._options([_make_summary(project_path=long_path)])
        self.assertIn(long_path[-40:], str(opts[0].prompt))

    def test_label_falls_back_to_dash_for_missing_project(self):
        opts = self._options([_make_summary(project_path=None)])
        self.assertIn("-", str(opts[0].prompt))


# _DetailModal.compose is not tested here: it opens a `with VerticalScroll(...)`
# context manager, which reaches for the active-app ContextVar and raises
# NoActiveAppError outside a mounted Textual app. SessionPickerScreen.compose
# only yields, so it is directly callable.


if __name__ == "__main__":
    unittest.main()
