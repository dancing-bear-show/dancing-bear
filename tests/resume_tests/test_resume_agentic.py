"""Tests for resume/agentic.py -- covering _flow_map branches and emit_agentic_context.

BUG NOTE (do not fix here -- report only):
_flow_map() line 35 calls _cli_path_exists([cmd]) where cmd is already a list
(e.g. ["extract"]), producing the nested path [["extract"]] instead of ["extract"].
The real _core_cli_path_exists never finds a subcommand whose name is the list
object ["extract"], so the main workflow block (lines 36-39) is unreachable via
the real parser. The bug is covered by test_first_three_calls_pass_nested_list
which asserts the observed (broken) call signature.
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
        self.assertIn("Cleanup workspace", result)

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
        self.assertNotIn("Cleanup workspace", result)

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
        self.assertNotIn("Cleanup workspace", result)

    def test_style_entry_only_when_style_path_true(self):
        def only_style(path: list) -> bool:
            return path == ["style"]

        with patch("resume.agentic._cli_path_exists", side_effect=only_style):
            import resume.agentic as mod
            result = mod._flow_map()
        self.assertIn("Style profile", result)
        self.assertNotIn("Align to job posting", result)

    def test_cleanup_entry_only_when_cleanup_path_true(self):
        def only_cleanup(path: list) -> bool:
            return path == ["cleanup"]

        with patch("resume.agentic._cli_path_exists", side_effect=only_cleanup):
            import resume.agentic as mod
            result = mod._flow_map()
        self.assertIn("Cleanup workspace", result)
        self.assertNotIn("Align to job posting", result)

    # -------------------------------------------------------------------------
    # Call-pattern: verifies the [cmd] wrapping produces nested-list arguments
    # -------------------------------------------------------------------------

    def test_first_call_passes_nested_list_path(self):
        """_cli_path_exists is called with [["extract"]] as the first argument
        (the [cmd] wrapping defect). all() short-circuits on False so only one
        nested-list call is made before falling through to the flat-list checks.

        BUG: line 35 uses [cmd] where cmd is already a list, so the first
        call passes a nested list instead of a flat string path. This test
        documents the observable defect so a fix surfaces here.
        """
        _, calls = self._patched_flow_map_collect(always=False)
        # 1 nested-list call (all() short-circuits) + 3 flat-list calls = 4 total
        self.assertEqual(len(calls), 4)
        # The defect: first call is a nested list
        self.assertEqual(calls[0], [["extract"]])
        # Last three calls are correct flat lists
        self.assertEqual(calls[1], ["align"])
        self.assertEqual(calls[2], ["style"])
        self.assertEqual(calls[3], ["cleanup"])


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
