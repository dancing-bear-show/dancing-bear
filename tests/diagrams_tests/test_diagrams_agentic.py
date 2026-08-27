"""Tests for diagrams agentic capsule and --agentic flag integration."""

import json
import unittest
from io import StringIO
from unittest.mock import patch

from tests.fixtures import capture_stdout


class TestDiagramsAgenticCapsule(unittest.TestCase):
    """Tests for diagrams/agentic.py."""

    def test_build_returns_string(self):
        from diagrams.agentic import build_agentic_capsule
        result = build_agentic_capsule()
        self.assertIsInstance(result, str)

    def test_contains_agentic_header(self):
        from diagrams.agentic import build_agentic_capsule
        self.assertIn("agentic: diagrams", build_agentic_capsule())

    def test_contains_from_yaml_command(self):
        from diagrams.agentic import build_agentic_capsule
        self.assertIn("from-yaml", build_agentic_capsule())

    def test_contains_render_command(self):
        from diagrams.agentic import build_agentic_capsule
        self.assertIn("render", build_agentic_capsule())

    def test_contains_validate_command(self):
        from diagrams.agentic import build_agentic_capsule
        self.assertIn("validate", build_agentic_capsule())

    def test_contains_embed_command(self):
        from diagrams.agentic import build_agentic_capsule
        self.assertIn("embed", build_agentic_capsule())

    def test_contains_telemetry_command(self):
        from diagrams.agentic import build_agentic_capsule
        self.assertIn("telemetry", build_agentic_capsule())

    def test_idempotent(self):
        from diagrams.agentic import build_agentic_capsule
        self.assertEqual(build_agentic_capsule(), build_agentic_capsule())

    def test_emit_returns_zero(self):
        from diagrams.agentic import emit_agentic_context
        with capture_stdout():
            rc = emit_agentic_context()
        self.assertEqual(rc, 0)

    def test_emit_accepts_fmt_and_compact(self):
        from diagrams.agentic import emit_agentic_context
        for fmt in ("text", "yaml", "json"):
            with capture_stdout():
                rc = emit_agentic_context(fmt, False)
            self.assertEqual(rc, 0)

    def test_emit_prints_capsule(self):
        from diagrams.agentic import build_agentic_capsule, emit_agentic_context
        with capture_stdout() as buf:
            emit_agentic_context()
        self.assertEqual(buf.getvalue(), build_agentic_capsule() + "\n")


class TestDiagramsAgenticFlag(unittest.TestCase):
    """Tests for --agentic flag in diagrams/cli.py main()."""

    def test_agentic_flag_exits_zero(self):
        from diagrams.cli import main
        with capture_stdout() as buf:
            rc = main(["--agentic"])
        self.assertEqual(rc, 0)
        self.assertIn("diagrams", buf.getvalue())

    def test_agentic_flag_yaml_format(self):
        from diagrams.cli import main
        with capture_stdout() as buf:
            rc = main(["--agentic", "--agentic-format", "yaml", "--agentic-compact"])
        self.assertEqual(rc, 0)
        self.assertIn("agentic: diagrams", buf.getvalue())

    def test_agentic_flag_json_format_valid_json(self):
        from diagrams.cli import main
        with capture_stdout() as buf:
            rc = main(["--agentic", "--agentic-format", "json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertIsInstance(parsed, dict)

    def test_no_subcommand_exits_zero(self):
        """Legacy exit code must remain 0 when no subcommand given."""
        from diagrams.cli import main
        with patch("sys.stdout", StringIO()):
            rc = main([])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
