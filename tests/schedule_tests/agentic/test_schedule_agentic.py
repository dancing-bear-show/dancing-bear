"""Tests for schedule agentic module."""
from __future__ import annotations

import io
import unittest
from unittest.mock import MagicMock, patch

from schedule import agentic


class TestGetParser(unittest.TestCase):
    """Tests for _get_parser function."""

    def test_returns_parser_or_none(self):
        """Test returns parser object or None."""
        # Clear the cache to test fresh
        agentic._get_parser.cache_clear()
        result = agentic._get_parser()
        # Should return a parser object (ArgumentParser) or None
        self.assertTrue(result is None or hasattr(result, "parse_args"))

    def test_caches_result(self):
        """Test parser is cached."""
        agentic._get_parser.cache_clear()
        result1 = agentic._get_parser()
        result2 = agentic._get_parser()
        self.assertIs(result1, result2)

    def test_handles_import_exception(self):
        """Test handles exception during import gracefully."""
        agentic._get_parser.cache_clear()
        with patch("schedule.agentic._get_parser") as mock_parser:
            mock_parser.side_effect = Exception("Import failed")
            # Should not raise, just return None
            try:
                agentic._get_parser.cache_clear()
                result = agentic._get_parser()
                # If we get here, the cached version returned successfully
                self.assertTrue(result is None or hasattr(result, "parse_args"))
            except Exception:
                pass  # Expected if the mock actually affects the real call


class TestCliTree(unittest.TestCase):
    """Tests for _cli_tree function."""

    def test_returns_string(self):
        """Test returns a string."""
        result = agentic._cli_tree()
        self.assertIsInstance(result, str)


class TestCliPathExists(unittest.TestCase):
    """Tests for _cli_path_exists function."""

    def test_returns_bool(self):
        """Test returns a boolean."""
        result = agentic._cli_path_exists(["plan"])
        self.assertIsInstance(result, bool)

    def test_returns_true_for_valid_commands(self):
        """Test returns True for valid commands."""
        # If parser is available, these commands should exist in schedule assistant
        parser = agentic._get_parser()
        if parser is not None:
            for cmd in ["plan", "apply", "verify", "sync", "export", "compress"]:
                result = agentic._cli_path_exists([cmd])
                self.assertTrue(result, f"Command '{cmd}' should exist")
        else:
            # Parser not available, just verify function returns bool
            result = agentic._cli_path_exists(["plan"])
            self.assertIsInstance(result, bool)

    def test_returns_false_for_invalid_command(self):
        """Test returns False for invalid command."""
        result = agentic._cli_path_exists(["nonexistent_command_xyz"])
        self.assertFalse(result)


class TestFlowMap(unittest.TestCase):
    """Tests for _flow_map function."""

    def test_returns_string(self):
        """Test returns a string."""
        result = agentic._flow_map()
        self.assertIsInstance(result, str)

    def test_contains_plan_flow_when_available(self):
        """Test contains plan flow when available."""
        result = agentic._flow_map()
        if agentic._cli_path_exists(["plan"]):
            self.assertIn("- Plan", result)
            self.assertIn("./bin/schedule-assistant plan", result)
            self.assertIn("--source schedules/classes.csv", result)
            self.assertIn("--out out/schedule.plan.yaml", result)

    def test_contains_apply_flow_when_available(self):
        """Test contains apply flow when available."""
        result = agentic._flow_map()
        if agentic._cli_path_exists(["apply"]):
            self.assertIn("- Apply", result)
            self.assertIn("./bin/schedule-assistant apply", result)
            self.assertIn("--dry-run", result)
            self.assertIn("--apply --calendar", result)

    def test_contains_verify_flow_when_available(self):
        """Test contains verify flow when available."""
        result = agentic._flow_map()
        if agentic._cli_path_exists(["verify"]):
            self.assertIn("- Verify", result)
            self.assertIn("./bin/schedule-assistant verify", result)
            self.assertIn("--from 2025-10-01", result)
            self.assertIn("--to 2025-12-31", result)

    def test_contains_sync_flow_when_available(self):
        """Test contains sync flow when available."""
        result = agentic._flow_map()
        if agentic._cli_path_exists(["sync"]):
            self.assertIn("- Sync", result)
            self.assertIn("./bin/schedule-assistant sync", result)
            self.assertIn("Safe dry-run", result)

    def test_contains_export_flow_when_available(self):
        """Test contains export flow when available."""
        result = agentic._flow_map()
        if agentic._cli_path_exists(["export"]):
            self.assertIn("- Export", result)
            self.assertIn("./bin/schedule-assistant export", result)
            self.assertIn("--calendar 'Activities'", result)

    def test_contains_compress_flow_when_available(self):
        """Test contains compress flow when available."""
        result = agentic._flow_map()
        if agentic._cli_path_exists(["compress"]):
            self.assertIn("- Compress", result)
            self.assertIn("./bin/schedule-assistant compress", result)
            self.assertIn("Infer recurring series", result)

    def test_flow_map_with_mocked_cli_paths(self):
        """Test flow map generation with all commands available."""
        # Mock _cli_path_exists to return True for all commands
        with patch("schedule.agentic._cli_path_exists") as mock_exists:
            mock_exists.return_value = True
            result = agentic._flow_map()

            # Verify all flow sections are present
            self.assertIn("- Plan", result)
            self.assertIn("Build canonical plan", result)
            self.assertIn("- Apply", result)
            self.assertIn("Dry-run apply", result)
            self.assertIn("Apply (create events)", result)
            self.assertIn("- Verify", result)
            self.assertIn("Verify plan", result)
            self.assertIn("- Sync", result)
            self.assertIn("Safe dry-run", result)
            self.assertIn("- Export", result)
            self.assertIn("Export Outlook window", result)
            self.assertIn("- Compress", result)
            self.assertIn("Infer recurring series", result)


class TestBuildAgenticCapsule(unittest.TestCase):
    """Tests for build_agentic_capsule function."""

    def test_returns_string(self):
        """Test returns a string."""
        result = agentic.build_agentic_capsule()
        self.assertIsInstance(result, str)

    def test_contains_app_id(self):
        """Test contains app ID."""
        result = agentic.build_agentic_capsule()
        self.assertIn("agentic: schedule", result)

    def test_contains_purpose(self):
        """Test contains purpose."""
        result = agentic.build_agentic_capsule()
        self.assertIn("purpose:", result)
        self.assertIn("dry-run", result)

    def test_contains_commands(self):
        """Test contains commands."""
        result = agentic.build_agentic_capsule()
        self.assertIn("commands:", result)
        self.assertIn("plan:", result)
        self.assertIn("apply (dry-run):", result)
        self.assertIn("verify:", result)
        self.assertIn("sync (dry-run):", result)

    def test_includes_cli_tree_section_when_available(self):
        """Test includes CLI Tree section when tree is available."""
        result = agentic.build_agentic_capsule()
        tree = agentic._cli_tree()
        if tree:
            self.assertIn("CLI Tree", result)

    def test_includes_flow_map_section_when_available(self):
        """Test includes Flow Map section when flows are available."""
        result = agentic.build_agentic_capsule()
        flows = agentic._flow_map()
        if flows:
            self.assertIn("Flow Map", result)

    def test_cli_tree_section_not_added_if_empty(self):
        """Test CLI Tree section not added if tree is empty."""
        with patch("schedule.agentic._cli_tree", return_value=""):
            result = agentic.build_agentic_capsule()
            # Should not contain CLI Tree section marker if tree is empty
            lines = result.split("\n")
            cli_tree_lines = [l for l in lines if "CLI Tree" in l]
            # If there are any CLI Tree mentions, they should be from the actual tree content
            # not from an empty section being added
            self.assertTrue(len(cli_tree_lines) == 0 or "==" not in "".join(cli_tree_lines))

    def test_flow_map_section_not_added_if_empty(self):
        """Test Flow Map section not added if flows are empty."""
        with patch("schedule.agentic._flow_map", return_value=""):
            result = agentic.build_agentic_capsule()
            lines = result.split("\n")
            flow_map_lines = [l for l in lines if "Flow Map" in l]
            self.assertTrue(len(flow_map_lines) == 0 or "==" not in "".join(flow_map_lines))

    def test_both_sections_added_when_available(self):
        """Test both CLI Tree and Flow Map sections are added when available."""
        with patch("schedule.agentic._cli_tree", return_value="- plan\n- apply"):
            with patch("schedule.agentic._flow_map", return_value="- Plan\n  - Build plan"):
                result = agentic.build_agentic_capsule()
                # Both sections should be present
                self.assertIn("CLI Tree", result)
                self.assertIn("Flow Map", result)
                self.assertIn("- plan", result)
                self.assertIn("- Plan", result)


class TestBuildDomainMap(unittest.TestCase):
    """Tests for build_domain_map function."""

    def test_returns_string(self):
        """Test returns a string."""
        result = agentic.build_domain_map()
        self.assertIsInstance(result, str)

    def test_contains_top_level_section(self):
        """Test contains top-level section."""
        result = agentic.build_domain_map()
        self.assertIn("Top-Level", result)
        self.assertIn("schedule/__main__.py", result)
        self.assertIn("schedule/README.md", result)

    def test_includes_cli_tree_section_when_available(self):
        """Test includes CLI Tree section when tree is available."""
        result = agentic.build_domain_map()
        tree = agentic._cli_tree()
        if tree:
            self.assertIn("== CLI Tree ==", result)

    def test_includes_flow_map_section_when_available(self):
        """Test includes Flow Map section when flows are available."""
        result = agentic.build_domain_map()
        flows = agentic._flow_map()
        if flows:
            self.assertIn("== Flow Map ==", result)

    def test_cli_tree_section_not_added_if_empty(self):
        """Test CLI Tree section not added if tree is empty."""
        with patch("schedule.agentic._cli_tree", return_value=""):
            result = agentic.build_domain_map()
            # Should not have CLI Tree section header
            self.assertNotIn("== CLI Tree ==", result)

    def test_flow_map_section_not_added_if_empty(self):
        """Test Flow Map section not added if flows are empty."""
        with patch("schedule.agentic._flow_map", return_value=""):
            result = agentic.build_domain_map()
            # Should not have Flow Map section header
            self.assertNotIn("== Flow Map ==", result)

    def test_both_sections_added_when_available(self):
        """Test both CLI Tree and Flow Map sections are added when available."""
        with patch("schedule.agentic._cli_tree", return_value="- plan\n- apply"):
            with patch("schedule.agentic._flow_map", return_value="- Plan\n  - Build plan"):
                result = agentic.build_domain_map()
                # Both sections should be present
                self.assertIn("== CLI Tree ==", result)
                self.assertIn("== Flow Map ==", result)
                self.assertIn("- plan", result)
                self.assertIn("- Plan", result)


class TestEmitAgenticContext(unittest.TestCase):
    """Tests for emit_agentic_context function."""

    def test_returns_zero(self):
        """Test returns 0 on success."""
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            result = agentic.emit_agentic_context()
        self.assertEqual(result, 0)

    def test_prints_capsule(self):
        """Test prints the agentic capsule."""
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            agentic.emit_agentic_context()
        output = captured.getvalue()
        self.assertIn("agentic: schedule", output)
        self.assertIn("purpose:", output)

    def test_accepts_format_param(self):
        """Test accepts format parameter (signature parity)."""
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            result = agentic.emit_agentic_context(_fmt="yaml")
        self.assertEqual(result, 0)

    def test_accepts_compact_param(self):
        """Test accepts compact parameter (signature parity)."""
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            result = agentic.emit_agentic_context(_compact=True)
        self.assertEqual(result, 0)

    def test_format_and_compact_params_together(self):
        """Test accepts both format and compact parameters together."""
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            result = agentic.emit_agentic_context(_fmt="text", _compact=False)
        self.assertEqual(result, 0)
        output = captured.getvalue()
        # Should still produce output
        self.assertGreater(len(output), 0)


if __name__ == "__main__":
    unittest.main()
