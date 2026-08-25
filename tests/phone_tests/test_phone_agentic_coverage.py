"""Expanded coverage tests for phone/agentic.py.

Strengthens the existing minimal tests by covering:
  - _flow_map conditional branches (all six True/False path combinations)
  - _cli_path_exists with known deep paths
  - build_agentic_capsule content assertions
  - build_domain_map content assertions
  - emit_agentic_context return value and output
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from phone import agentic as _agentic_module


class TestCliPathExists(unittest.TestCase):
    """Tests for _cli_path_exists."""

    def test_nonexistent_top_level_returns_false(self):
        from phone.agentic import _cli_path_exists

        self.assertFalse(_cli_path_exists(["nonexistent_command_xyz"]))

    def test_returns_bool(self):
        from phone.agentic import _cli_path_exists

        result = _cli_path_exists(["plan"])
        self.assertIsInstance(result, bool)

    def test_two_element_nonexistent_path_returns_false(self):
        from phone.agentic import _cli_path_exists

        self.assertFalse(_cli_path_exists(["nonexistent", "also_nonexistent"]))


class TestFlowMapConditionalBranches(unittest.TestCase):
    """Test _flow_map branches by mocking _cli_path_exists.

    Each test controls which CLI paths exist and asserts on the sections
    included or excluded from the flow map output.
    """

    def _flow_map_with(self, true_paths: list[list[str]]) -> str:
        """Run _flow_map with a controlled set of existing paths."""
        def exists(path: list[str]) -> bool:
            return path in true_paths

        with patch.object(_agentic_module, "_cli_path_exists", side_effect=exists):
            return _agentic_module._flow_map()

    def test_all_paths_true_includes_all_sections(self):
        all_paths = [
            ["export-device"], ["iconmap"], ["plan"], ["checklist"],
            ["auto-folders"], ["analyze"],
            ["profile", "build"],
            ["manifest", "create"], ["manifest", "install"],
        ]
        result = self._flow_map_with(all_paths)
        self.assertIn("Layout workflow", result)
        self.assertIn("Layout insights", result)
        self.assertIn("Profiles", result)
        self.assertIn("Device snapshot", result)
        self.assertIn("Manifests", result)
        self.assertIn("Install profile", result)

    def test_no_paths_true_returns_empty_string(self):
        result = self._flow_map_with([])
        self.assertEqual(result, "")

    def test_layout_workflow_section_requires_all_four_cmds(self):
        # Only three of the four layout cmds — section should NOT appear
        partial = [["export-device"], ["iconmap"], ["plan"]]
        result = self._flow_map_with(partial)
        self.assertNotIn("Layout workflow", result)

    def test_analyze_only_adds_layout_insights_section(self):
        result = self._flow_map_with([["analyze"]])
        self.assertIn("Layout insights", result)
        self.assertIn("Analyze balance", result)
        self.assertNotIn("Auto folders", result)

    def test_auto_folders_only_adds_layout_insights_section(self):
        result = self._flow_map_with([["auto-folders"]])
        self.assertIn("Layout insights", result)
        self.assertIn("Auto folders", result)
        self.assertNotIn("Analyze balance", result)

    def test_profile_build_adds_profiles_section(self):
        result = self._flow_map_with([["profile", "build"]])
        self.assertIn("Profiles", result)
        self.assertIn("mobileconfig", result)

    def test_export_device_alone_adds_device_snapshot_section(self):
        result = self._flow_map_with([["export-device"]])
        self.assertIn("Device snapshot", result)

    def test_manifest_create_without_install_excludes_install_line(self):
        result = self._flow_map_with([["manifest", "create"]])
        self.assertIn("Manifests", result)
        self.assertIn("Create manifest", result)
        self.assertNotIn("Install profile", result)

    def test_manifest_install_requires_manifest_create_to_appear(self):
        # manifest install check is inside the manifest create block
        result = self._flow_map_with([["manifest", "install"]])
        # manifest create is False, so the whole Manifests block is skipped
        self.assertNotIn("Manifests", result)

    def test_manifest_create_and_install_both_appear(self):
        result = self._flow_map_with([["manifest", "create"], ["manifest", "install"]])
        self.assertIn("Install profile", result)


class TestFlowMapReturnType(unittest.TestCase):
    def test_returns_string(self):
        from phone.agentic import _flow_map

        result = _flow_map()
        self.assertIsInstance(result, str)


class TestCliTree(unittest.TestCase):
    def test_returns_string(self):
        from phone.agentic import _cli_tree

        result = _cli_tree()
        self.assertIsInstance(result, str)


class TestBuildAgenticCapsule(unittest.TestCase):
    def test_returns_string(self):
        from phone.agentic import build_agentic_capsule

        result = build_agentic_capsule()
        self.assertIsInstance(result, str)

    def test_contains_domain_name(self):
        from phone.agentic import build_agentic_capsule

        result = build_agentic_capsule()
        self.assertIn("phone", result)

    def test_contains_purpose_text(self):
        from phone.agentic import build_agentic_capsule

        result = build_agentic_capsule()
        self.assertIn("layout", result.lower())

    def test_contains_export_device_command(self):
        from phone.agentic import build_agentic_capsule

        result = build_agentic_capsule()
        self.assertIn("export-device", result)

    def test_contains_plan_command(self):
        from phone.agentic import build_agentic_capsule

        result = build_agentic_capsule()
        self.assertIn("plan", result)


class TestBuildDomainMap(unittest.TestCase):
    def test_returns_non_empty_string(self):
        from phone.agentic import build_domain_map

        result = build_domain_map()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_contains_phone_module_references(self):
        from phone.agentic import build_domain_map

        result = build_domain_map()
        self.assertIn("phone", result.lower())

    def test_contains_layout_reference(self):
        from phone.agentic import build_domain_map

        result = build_domain_map()
        self.assertIn("layout", result.lower())


class TestEmitAgenticContext(unittest.TestCase):
    def test_returns_zero(self):
        from phone.agentic import emit_agentic_context

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = emit_agentic_context()
        self.assertEqual(rc, 0)

    def test_prints_phone_capsule(self):
        from phone.agentic import emit_agentic_context

        buf = io.StringIO()
        with redirect_stdout(buf):
            emit_agentic_context()
        self.assertIn("phone", buf.getvalue())

    def test_fmt_and_compact_params_accepted(self):
        from phone.agentic import emit_agentic_context

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = emit_agentic_context(_fmt="json", _compact=True)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
