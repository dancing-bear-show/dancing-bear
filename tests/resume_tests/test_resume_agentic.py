"""Tests for resume/agentic.py -- covering _flow_map branches and emit_agentic_context.

Two stacked bugs, both now fixed, are pinned here:

1. ``_load_parser`` imported a module-level ``build_parser`` that does not
   exist (the CLI is built with the CLIApp framework). ``cached_parser_loader``
   swallowed the ImportError, so ``_get_parser()`` returned None and the
   capsule silently shipped with no CLI Tree and no Flow Map.
2. ``_flow_map`` called ``_cli_path_exists([cmd])`` where ``cmd`` was already
   ``["extract"]``, producing ``[["extract"]]``. That raises TypeError from
   ``choices.get(name)`` -- a list is unhashable -- so fixing only the parser
   would have turned a silent empty capsule into a crashing one.

Bug 1 masked bug 2: with the parser None, ``cli_path_exists`` returned at its
``parser is None`` guard and never reached the dict lookup.

Repo-wide coverage for the first failure mode lives in
``tests/core_tests/test_agentic_parser_wiring.py``, which asserts that every
domain declaring a ``_get_parser`` actually resolves one.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tests.fixtures import capture_stdout


class TestResumeFlowMapBranches(unittest.TestCase):
    """_flow_map() call patterns and branch coverage for all four if-guards."""

    def _patched_flow_map_collect(self, always: bool) -> tuple[str, list]:
        """Run _flow_map, returning (output, list of paths _cli_path_exists was called with)."""
        recorded: list = []

        def fake_exists(path: list) -> bool:
            recorded.append(list(path))  # snapshot so mutation doesn't affect us
            return always

        with patch("resume.agentic._cli_path_exists", side_effect=fake_exists):
            import resume.agentic as mod
            result = mod._flow_map()
        return result, recorded

    # -------------------------------------------------------------------------
    # Happy-path: all calls return True
    # -------------------------------------------------------------------------

    def test_all_true_renders_all_four_entries(self):
        """When every _cli_path_exists call returns True all four entries are present."""
        result, _ = self._patched_flow_map_collect(always=True)
        self.assertIn("Resume workflow", result)
        self.assertIn("Align to job posting", result)
        self.assertIn("Style profile", result)
        self.assertIn("Tidy workspace", result)

    def test_all_true_main_workflow_contains_three_commands(self):
        result, _ = self._patched_flow_map_collect(always=True)
        self.assertIn("extract --linkedin", result)
        self.assertIn("summarize --data", result)
        self.assertIn("render --data", result)

    # -------------------------------------------------------------------------
    # Sad-path: all calls return False
    # -------------------------------------------------------------------------

    def test_all_false_returns_empty_string(self):
        """When every _cli_path_exists call returns False the result is empty."""
        result, _ = self._patched_flow_map_collect(always=False)
        self.assertEqual(result, "")

    def test_all_false_no_workflow_entries(self):
        result, _ = self._patched_flow_map_collect(always=False)
        self.assertNotIn("Resume workflow", result)
        self.assertNotIn("Align to job posting", result)
        self.assertNotIn("Style profile", result)
        self.assertNotIn("Tidy workspace", result)

    # -------------------------------------------------------------------------
    # Selective happy/sad: each simple branch independently
    # -------------------------------------------------------------------------

    def test_align_entry_only_when_align_path_true(self):
        """Align entry appears when _cli_path_exists returns True for the align call."""
        def only_align(path: list) -> bool:
            return path == ["align"]

        with patch("resume.agentic._cli_path_exists", side_effect=only_align):
            import resume.agentic as mod
            result = mod._flow_map()
        self.assertIn("Align to job posting", result)
        self.assertNotIn("Style profile", result)
        self.assertNotIn("Tidy workspace", result)

    def test_style_entry_only_when_style_path_true(self):
        def only_style(path: list) -> bool:
            return path == ["style", "build"]

        with patch("resume.agentic._cli_path_exists", side_effect=only_style):
            import resume.agentic as mod
            result = mod._flow_map()
        self.assertIn("Style profile", result)
        self.assertNotIn("Align to job posting", result)

    def test_tidy_entry_only_when_files_tidy_path_true(self):
        def only_tidy(path: list) -> bool:
            return path == ["files", "tidy"]

        with patch("resume.agentic._cli_path_exists", side_effect=only_tidy):
            import resume.agentic as mod
            result = mod._flow_map()
        self.assertIn("Tidy workspace", result)
        self.assertNotIn("Align to job posting", result)

    # -------------------------------------------------------------------------
    # Call-pattern: every _cli_path_exists call passes a flat path
    # -------------------------------------------------------------------------

    def test_every_call_passes_a_flat_path(self):
        """No call may pass a nested list.

        This test previously ASSERTED the defect: ``_flow_map`` used
        ``_cli_path_exists([cmd])`` where ``cmd`` was already ``["extract"]``,
        so the first call received ``[["extract"]]``. It was written to
        document the bug so a fix would surface here -- and it did.

        The nested form is not merely wrong-but-harmless: ``cli_path_exists``
        does ``choices.get(name)``, and a list is unhashable, so it raises
        TypeError. It only looked benign because the parser was ALSO None at
        the time, short-circuiting before the lookup. Both bugs had to be fixed
        together; fixing the parser alone would have crashed the capsule.
        """
        _, calls = self._patched_flow_map_collect(always=False)
        # all() short-circuits on the first False, so only one of the three
        # workflow probes runs, then the three standalone checks.
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0], ["extract"])
        self.assertEqual(calls[1], ["align"])
        self.assertEqual(calls[2], ["style", "build"])
        self.assertEqual(calls[3], ["files", "tidy"])
        for call in calls:
            for element in call:
                self.assertIsInstance(
                    element, str, f"nested path leaked back in: {call!r}"
                )


class TestResumeEmitAgenticContext(unittest.TestCase):
    """emit_agentic_context() with different _fmt and _compact arguments."""

    def test_emit_default_returns_zero(self):
        import resume.agentic as mod
        with capture_stdout():
            rc = mod.emit_agentic_context()
        self.assertEqual(rc, 0)

    def test_emit_fmt_yaml_returns_zero(self):
        import resume.agentic as mod
        with capture_stdout():
            rc = mod.emit_agentic_context(_fmt="yaml")
        self.assertEqual(rc, 0)

    def test_emit_compact_true_returns_zero(self):
        import resume.agentic as mod
        with capture_stdout():
            rc = mod.emit_agentic_context(_compact=True)
        self.assertEqual(rc, 0)

    def test_emit_output_contains_capsule_header(self):
        import resume.agentic as mod
        with capture_stdout() as buf:
            mod.emit_agentic_context()
        self.assertIn("agentic: resume", buf.getvalue())

    def test_emit_compact_output_contains_capsule_header(self):
        import resume.agentic as mod
        with capture_stdout() as buf:
            mod.emit_agentic_context(_compact=True)
        self.assertIn("agentic: resume", buf.getvalue())


class TestResumeBuildAgenticCapsule(unittest.TestCase):
    """build_agentic_capsule() returns a well-formed capsule string."""

    def test_capsule_contains_app_id(self):
        import resume.agentic as mod
        result = mod.build_agentic_capsule()
        self.assertIn("agentic: resume", result)

    def test_capsule_contains_key_commands(self):
        import resume.agentic as mod
        result = mod.build_agentic_capsule()
        self.assertIn("extract", result)
        self.assertIn("summarize", result)
        self.assertIn("render", result)
        self.assertIn("align", result)

    def test_capsule_is_string(self):
        import resume.agentic as mod
        self.assertIsInstance(mod.build_agentic_capsule(), str)


class TestResumeBuildDomainMap(unittest.TestCase):
    """build_domain_map() returns a non-empty domain map string."""

    def test_domain_map_is_string(self):
        import resume.agentic as mod
        self.assertIsInstance(mod.build_domain_map(), str)

    def test_domain_map_contains_top_level_heading(self):
        import resume.agentic as mod
        self.assertIn("Top-Level", mod.build_domain_map())


if __name__ == "__main__":
    unittest.main(verbosity=2)
