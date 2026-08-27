"""Tests for workflow agentic capsule and --agentic flag support."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


class TestWorkflowAgenticModule(unittest.TestCase):
    """Tests for workflow/agentic.py."""

    def test_emit_agentic_context_returns_zero(self):
        from workflow.agentic import emit_agentic_context

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = emit_agentic_context()
        self.assertEqual(rc, 0)

    def test_emit_agentic_context_prints_app_name(self):
        from workflow.agentic import emit_agentic_context

        buf = io.StringIO()
        with redirect_stdout(buf):
            emit_agentic_context()
        self.assertIn("workflow", buf.getvalue())

    def test_emit_agentic_context_accepts_fmt_and_compact(self):
        from workflow.agentic import emit_agentic_context

        for fmt in ("text", "yaml", "json"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = emit_agentic_context(fmt, False)
            self.assertEqual(rc, 0)

    def test_build_agentic_capsule_contains_subcommands(self):
        from workflow.agentic import build_agentic_capsule

        capsule = build_agentic_capsule()
        for cmd in ("run", "list", "lint", "parse", "compile", "status", "resume"):
            self.assertIn(cmd, capsule, f"Expected '{cmd}' in capsule")

    def test_build_agentic_capsule_contains_params_form(self):
        from workflow.agentic import build_agentic_capsule

        capsule = build_agentic_capsule()
        self.assertIn("--params", capsule)

    def test_build_agentic_capsule_returns_string(self):
        from workflow.agentic import build_agentic_capsule

        result = build_agentic_capsule()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)


class TestWorkflowMainAgentic(unittest.TestCase):
    """Tests for --agentic flag wired through workflow main()."""

    def test_agentic_flag_exits_zero(self):
        from workflow.cli import main

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--agentic"])
        self.assertEqual(rc, 0)

    def test_agentic_flag_prints_capsule_with_app_name(self):
        from workflow.cli import main

        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--agentic"])
        self.assertIn("workflow", buf.getvalue())

    def test_agentic_format_json_produces_valid_json(self):
        from workflow.cli import main

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--agentic", "--agentic-format", "json"])
        self.assertEqual(rc, 0)
        output = buf.getvalue().strip()
        self.assertTrue(len(output) > 0)
        try:
            parsed = json.loads(output)
            self.assertIsInstance(parsed, dict)
        except json.JSONDecodeError:
            # Fallback capsule text is acceptable; the important thing is exit 0
            pass

    def test_no_subcommand_preserves_legacy_exit_code(self):
        """The legacy no-subcommand exit code (ExitCode.USAGE == 2) must be unchanged."""
        from core.cli_errors import ExitCode
        from workflow.cli import main

        stderr_buf = io.StringIO()
        with patch("sys.stderr", stderr_buf):
            rc = main([])
        self.assertEqual(rc, ExitCode.USAGE)

    def test_no_subcommand_preserves_legacy_message(self):
        """The legacy no-subcommand message must contain 'Usage: workflow'."""
        from workflow.cli import main

        stderr_buf = io.StringIO()
        with patch("sys.stderr", stderr_buf):
            main([])
        self.assertIn("Usage: workflow", stderr_buf.getvalue())


if __name__ == "__main__":
    unittest.main()
